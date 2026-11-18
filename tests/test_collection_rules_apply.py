"""The apply removes every membership whose survey is not a curriculum and nothing else (intake
report #128, story curricula-order 2.3)."""

import importlib
import uuid

import pytest
from django.apps import apps as django_apps
from django.db import migrations, transaction
from django.db.migrations.loader import MigrationLoader
from django.test import override_settings
from django.utils.timezone import now

from survey_collections import rule_report
from survey_collections.models import CollectionMembership, SurveyCollection
from surveys.models import Survey

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")

pytestmark = pytest.mark.django_db


def _survey(survey_type="curriculum", deleted=False):
    return Survey.objects.create(
        organization_id=ORG, survey_type=survey_type, deleted_at=now() if deleted else None
    )


def _collection(*members, deleted=False):
    collection = SurveyCollection.objects.create(organization_id=ORG, deleted_at=now() if deleted else None)
    for survey in members:
        collection.append_member(survey)
    return collection


def _members():
    return sorted(CollectionMembership._base_manager.values_list("id", "surveycollection_id", "survey_id", "order"))


def _parents():
    return (
        sorted(SurveyCollection._base_manager.values_list()),
        sorted(Survey._base_manager.values_list("id", "survey_type", "deleted_at", "organization_id")),
    )


def _forwards():
    return importlib.import_module("survey_collections.migrations.0018_remove_non_curriculum_members").forwards


def _apply(capsys, apps=django_apps):
    _forwards()(apps, None)
    return capsys.readouterr().out


def test_non_curricula_removed_with_one_line_each(capsys):
    curriculum, exam, form = _survey(), _survey("exam"), _survey("form")
    c = _collection(curriculum, exam, form)

    out = _apply(capsys)

    assert list(CollectionMembership.objects.values_list("survey_id", flat=True)) == [curriculum.id]
    assert f"collection-rules: removed: collection {c.id} survey {exam.id} order 1 (exam)" in out
    assert f"collection-rules: removed: collection {c.id} survey {form.id} order 2 (form)" in out
    assert "collection-rules: removed: 2\n" in out
    assert "collection-rules: removed: exam: 1" in out
    assert "collection-rules: removed: form: 1" in out


def test_curricula_keep_their_ids_and_orders(capsys):
    a, b, exam, d = _survey(), _survey(), _survey("exam"), _survey()
    c = _collection(a, exam, b, d)
    CollectionMembership.objects.filter(surveycollection=c, survey=b).update(order=2)
    CollectionMembership.objects.filter(surveycollection=c, survey=d).update(order=0)
    CollectionMembership.objects.filter(surveycollection=c, survey=a).update(order=1)
    CollectionMembership.objects.filter(surveycollection=c, survey=exam).update(order=1)
    kept = [row for row in _members() if row[2] != exam.id]

    _apply(capsys)

    assert _members() == kept


def test_links_under_deleted_parents_removed_too(capsys):
    in_deleted = _survey("exam")
    _collection(_survey(), in_deleted, deleted=True)
    deleted_exam = _survey("exam", deleted=True)
    _collection(_survey(), deleted_exam)

    out = _apply(capsys)

    remaining = set(CollectionMembership._base_manager.values_list("survey_id", flat=True))
    assert in_deleted.id not in remaining and deleted_exam.id not in remaining
    assert len(remaining) == 2
    assert "collection-rules: removed: exam: 2" in out


def test_clean_data_deletes_nothing(capsys):
    _collection(_survey(), _survey())
    _collection(_survey())
    before = _members()

    out = _apply(capsys)

    assert _members() == before
    assert "collection-rules: removed: 0\n" in out
    assert "collection-rules: removed: collection" not in out


def test_surveys_and_collections_unchanged(capsys):
    shared = _survey()
    _collection(shared, _survey("exam"), _survey("form", deleted=True))
    _collection(shared, _survey("assessment"), deleted=True)
    before = _parents()

    _apply(capsys)

    assert _parents() == before


def test_report_rerun_after_apply_has_no_non_curricula(capsys):
    shared = _survey()
    _collection(shared, _survey("exam"), _survey(""))
    _collection(shared, _survey("form", deleted=True), deleted=True)

    out = _apply(capsys)

    lines = out.strip("\n").splitlines()
    assert lines[0] == "  collection-rules: apply (remove non-curriculum members)"
    assert all(line.startswith("  collection-rules: ") for line in lines)
    assert "collection-rules: removed: (no type): 1" in out
    assert "collection-rules: after apply: all: not curricula: 0" in out
    assert "collection-rules: after apply: shown: not curricula: 0" in out
    # The one-collection rule is reported but not applied.
    assert "collection-rules: after apply: all: curricula in more than one collection: 1" in out


def test_apply_depends_on_the_report_and_has_a_noop_reverse():
    # pytest.ini's --no-migrations blanks MIGRATION_MODULES; read the graph from disk.
    with override_settings(MIGRATION_MODULES={}):
        loader = MigrationLoader(None, ignore_no_migrations=True)
    migration = loader.get_migration("survey_collections", "0018_remove_non_curriculum_members")

    assert ("survey_collections", "0017_report_rule_breaking_members") in migration.dependencies
    assert migration.operations[0].reverse_code is migrations.RunPython.noop


def test_one_exam_in_two_collections_loses_both_links(capsys):
    exam = _survey("exam")
    first, second = _collection(_survey(), exam), _collection(exam)

    out = _apply(capsys)

    assert not CollectionMembership._base_manager.filter(survey=exam).exists()
    assert f"collection-rules: removed: collection {first.id} survey {exam.id} order 1 (exam)" in out
    assert f"collection-rules: removed: collection {second.id} survey {exam.id} order 0 (exam)" in out
    assert "collection-rules: removed: exam: 2" in out


def test_count_mismatch_raises_and_rolls_back(monkeypatch):
    _collection(_survey(), _survey("exam"))
    before = _members()
    found = rule_report.find_not_curricula
    missing = max(row[0] for row in before) + 1000
    monkeypatch.setattr(
        rule_report,
        "find_not_curricula",
        lambda model=None, reference_model=None: [*found(model, reference_model), rule_report.Breaker(missing, 0, 0, 0, "exam")],
    )

    with pytest.raises(RuntimeError, match="removed 1 memberships, expected 2"):
        with transaction.atomic():
            rule_report.apply()

    assert _members() == before


def test_forwards_runs_on_the_historical_models(capsys):
    curriculum, exam = _survey(), _survey("exam")
    _collection(curriculum, exam)
    with override_settings(MIGRATION_MODULES={}):
        loader = MigrationLoader(None, ignore_no_migrations=True)
    historical = loader.project_state(("survey_collections", "0018_remove_non_curriculum_members")).apps

    out = _apply(capsys, historical)

    assert list(CollectionMembership._base_manager.values_list("survey_id", flat=True)) == [curriculum.id]
    assert "collection-rules: removed: exam: 1" in out
