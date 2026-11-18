"""The restore recreates only the 5 course exam links 0018 removed, each when its collection is a
course collection and the link is absent (intake report #128, story curricula-order 2.4)."""

import importlib
import uuid

import pytest
from django.apps import apps as django_apps
from django.db import migrations
from django.db.migrations.loader import MigrationLoader
from django.test import override_settings
from django.utils.timezone import now

from external_references.models import ExternalReference
from survey_collections.models import CollectionMembership, SurveyCollection
from surveys.models import Survey

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")
NAME = "0019_restore_course_exam_links"
PAIRS = [(23, 179, 0), (24, 201, 0), (31, 198, 0), (134, 199, 0), (134, 200, 1)]

pytestmark = pytest.mark.django_db


def _survey(pk, survey_type="exam", deleted=False):
    return Survey.objects.create(
        pk=pk, organization_id=ORG, survey_type=survey_type, deleted_at=now() if deleted else None
    )


def _collection(pk, course=True, deleted=False, type="exam"):
    collection = SurveyCollection.objects.create(
        pk=pk, organization_id=ORG, type=type, deleted_at=now() if deleted else None
    )
    if course:
        ExternalReference.objects.create(
            source_service="courses", source_model="course", source_id=str(pk), collection=collection
        )
    return collection


def _all_present(deleted=False):
    for cid in (23, 24, 31, 134):
        _collection(cid, deleted=deleted)
    for sid in (179, 201, 198, 199, 200):
        _survey(sid, deleted=deleted)


def _members():
    return sorted(CollectionMembership._base_manager.values_list("surveycollection_id", "survey_id", "order"))


def _restore(capsys, apps=django_apps):
    importlib.import_module(f"survey_collections.migrations.{NAME}").forwards(apps, None)
    return capsys.readouterr().out


def test_all_restorable_restored_with_logged_order(capsys):
    _all_present()

    out = _restore(capsys)

    assert _members() == sorted(PAIRS)
    for cid, sid, order in PAIRS:
        assert f"  collection-rules: restored: collection {cid} survey {sid} order {order} (exam)\n" in out
    assert "order shared" not in out
    assert "collection-rules: restored: 5\n" in out
    assert "collection-rules: skipped: 0\n" in out
    # Course-collection exams are outside the rules, so the report re-run counts none of them.
    assert "collection-rules: after restore: all: not curricula: 0" in out
    assert "collection-rules: after restore: shown: not curricula: 0" in out


def test_existing_link_kept_with_its_order(capsys):
    _all_present()
    CollectionMembership.objects.create(surveycollection_id=134, survey_id=199, order=3)

    out = _restore(capsys)

    assert CollectionMembership.objects.get(surveycollection_id=134, survey_id=199).order == 3
    assert "collection-rules: skipped: collection 134 survey 199 (link exists) (exam)\n" in out
    assert "collection-rules: restored: 4\n" in out
    assert "collection-rules: skipped: 1\n" in out


def test_missing_collection_and_survey_skipped(capsys):
    # No collection 23 (survey 179 exists); no survey 201 (collection 24 exists).
    for cid in (24, 31, 134):
        _collection(cid)
    for sid in (179, 198, 199, 200):
        _survey(sid)

    out = _restore(capsys)

    assert not CollectionMembership._base_manager.filter(survey_id__in=[179, 201]).exists()
    assert "collection-rules: skipped: collection 23 survey 179 (collection missing) (exam)\n" in out
    assert "collection-rules: skipped: collection 24 survey 201 (survey missing)\n" in out
    assert "collection-rules: restored: 3\n" in out
    assert "collection-rules: skipped: 2\n" in out


def test_exam_typed_collection_without_courses_reference_skipped(capsys):
    for cid in (23, 24, 134):
        _collection(cid)
    other = _collection(31, course=False, type="exam")
    ExternalReference.objects.create(source_service="articles", source_model="course", source_id="31", collection=other)
    for sid in (179, 201, 198, 199, 200):
        _survey(sid)

    out = _restore(capsys)

    assert not CollectionMembership._base_manager.filter(surveycollection_id=31).exists()
    assert "collection-rules: skipped: collection 31 survey 198 (not a course collection) (exam)\n" in out
    assert "collection-rules: restored: 4\n" in out


def test_soft_deleted_rows_still_restored(capsys):
    _all_present(deleted=True)

    out = _restore(capsys)

    assert _members() == sorted(PAIRS)
    assert "collection-rules: restored: 5\n" in out


def test_others_untouched_and_no_renumbering(capsys):
    _all_present()
    # A course exam appended after 2.3 ran, at the order a restored pair takes.
    _survey(500)
    CollectionMembership.objects.create(surveycollection_id=23, survey_id=500, order=0)
    curriculum = _survey(501, "curriculum")
    elsewhere = _collection(900, course=False, type=None)
    CollectionMembership.objects.create(surveycollection=elsewhere, survey=curriculum, order=0)
    others = _members()
    parents = (
        sorted(SurveyCollection._base_manager.values_list()),
        sorted(Survey._base_manager.values_list("id", "survey_type", "deleted_at", "organization_id")),
    )

    out = _restore(capsys)

    assert "collection-rules: restored: collection 23 survey 179 order 0 (exam) order shared\n" in out
    assert "collection-rules: restored: collection 134 survey 199 order 0 (exam)\n" in out
    assert sorted(set(_members()) - set(PAIRS)) == others
    assert parents == (
        sorted(SurveyCollection._base_manager.values_list()),
        sorted(Survey._base_manager.values_list("id", "survey_type", "deleted_at", "organization_id")),
    )


def test_empty_database_skips_all_five(capsys):
    out = _restore(capsys)

    assert _members() == []
    lines = out.strip("\n").splitlines()
    assert all(line.startswith("  collection-rules: ") for line in lines)
    assert sum(" skipped: collection " in line for line in lines) == 5
    assert "collection-rules: restored: 0\n" in out
    assert "collection-rules: skipped: 5\n" in out


def test_depends_on_the_apply_and_has_a_noop_reverse():
    # pytest.ini's --no-migrations blanks MIGRATION_MODULES; read the graph from disk.
    with override_settings(MIGRATION_MODULES={}):
        loader = MigrationLoader(None, ignore_no_migrations=True)
    migration = loader.get_migration("survey_collections", NAME)

    assert ("survey_collections", "0018_remove_non_curriculum_members") in migration.dependencies
    assert ("external_references", "0001_initial") in migration.dependencies
    assert ("surveys", "0062_apply_default_language_relabel") in migration.dependencies
    assert migration.operations[0].reverse_code is migrations.RunPython.noop


def test_forwards_runs_on_the_historical_models(capsys):
    _all_present(deleted=True)
    with override_settings(MIGRATION_MODULES={}):
        loader = MigrationLoader(None, ignore_no_migrations=True)
    historical = loader.project_state(("survey_collections", NAME)).apps

    out = _restore(capsys, historical)

    assert _members() == sorted(PAIRS)
    assert "collection-rules: restored: 5\n" in out


def test_link_created_concurrently_is_skipped_not_failed(capsys, monkeypatch):
    _all_present()
    manager = type(CollectionMembership._base_manager)
    original = manager.get_or_create

    def racing(self, defaults=None, **kwargs):
        if kwargs == {"surveycollection_id": 31, "survey_id": 198}:
            CollectionMembership.objects.create(surveycollection_id=31, survey_id=198, order=7)
        return original(self, defaults=defaults, **kwargs)

    monkeypatch.setattr(manager, "get_or_create", racing)

    out = _restore(capsys)

    assert CollectionMembership.objects.get(surveycollection_id=31, survey_id=198).order == 7
    assert "collection-rules: skipped: collection 31 survey 198 (link exists) (exam)\n" in out
    assert "collection-rules: restored: 4\n" in out
    assert "collection-rules: skipped: 1\n" in out


def test_restore_is_the_single_survey_collections_leaf():
    # pytest.ini's --no-migrations blanks MIGRATION_MODULES; read the graph from disk.
    with override_settings(MIGRATION_MODULES={}):
        loader = MigrationLoader(None, ignore_no_migrations=True)

    assert loader.graph.leaf_nodes("survey_collections") == [("survey_collections", NAME)]
