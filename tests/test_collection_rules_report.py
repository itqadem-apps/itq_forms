"""The report counts the memberships that break the collection rules and writes nothing (intake
report #128, story curricula-order 2.1)."""

import importlib
import uuid

import pytest
from django.apps import apps as django_apps
from django.db import migrations
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


def _state():
    return (
        sorted(CollectionMembership._base_manager.values_list("id", "surveycollection_id", "survey_id", "order")),
        sorted(SurveyCollection._base_manager.values_list("id", "deleted_at")),
        sorted(Survey._base_manager.values_list("id", "survey_type", "deleted_at")),
    )


def _report(capsys):
    importlib.import_module("survey_collections.migrations.0017_report_rule_breaking_members").forwards(django_apps, None)
    return capsys.readouterr().out


def test_non_curricula_counted_by_type(capsys):
    _collection(_survey(), _survey("exam"), _survey("exam"), _survey("form"))

    out = _report(capsys)

    for scope in ("all", "shown"):
        assert f"collection-rules: {scope}: not curricula: 3" in out
        assert f"collection-rules: {scope}: exam: 2" in out
        assert f"collection-rules: {scope}: form: 1" in out
        assert f"collection-rules: {scope}: curricula in more than one collection: 0" in out


def test_shared_curriculum_counted_with_its_ids(capsys):
    c, d = _survey(), _survey()
    _collection(c, d)
    _collection(c)

    found = rule_report.find()
    out = _report(capsys)

    assert found.all.shared_curricula == [c.id]
    assert found.shown.shared_curricula == [c.id]
    for scope in ("all", "shown"):
        assert f"collection-rules: {scope}: curricula in more than one collection: 1" in out
        assert f"collection-rules: {scope}: shared curricula ids: {c.id}" in out
        assert f"collection-rules: {scope}: not curricula: 0" in out


def test_deleted_counted_under_all_not_shown():
    _collection(_survey(), _survey("exam", deleted=True))
    shared = _survey()
    _collection(shared)
    _collection(shared, _survey("form"), deleted=True)

    found = rule_report.find()

    assert found.all.not_curricula == {"exam": 1, "form": 1}
    assert found.all.shared_curricula == [shared.id]
    assert found.shown.not_curricula == {}
    assert found.shown.shared_curricula == []


def test_clean_data_counts_zero(capsys):
    _collection(_survey(), _survey())
    _collection(_survey())

    out = _report(capsys)

    assert out.count("collection-rules: ") == 5
    for scope in ("all", "shown"):
        assert f"collection-rules: {scope}: not curricula: 0" in out
        assert f"collection-rules: {scope}: curricula in more than one collection: 0" in out
    assert "shared curricula ids" not in out


def test_report_migration_writes_nothing(capsys):
    shared = _survey()
    _collection(shared, _survey("exam"), _survey("form", deleted=True))
    _collection(shared, _survey("assessment"), deleted=True)
    before = _state()

    out = _report(capsys)

    assert _state() == before
    assert "collection-rules: report (nothing written)" in out
    assert all(line.startswith("  collection-rules: ") for line in out.strip("\n").splitlines())


def test_report_runs_after_the_surveys_it_reads():
    # pytest.ini's --no-migrations blanks MIGRATION_MODULES; read the graph from disk.
    with override_settings(MIGRATION_MODULES={}):
        loader = MigrationLoader(None, ignore_no_migrations=True)
    migration = loader.get_migration("survey_collections", "0017_report_rule_breaking_members")

    assert ("survey_collections", "0016_collection_member_order") in migration.dependencies
    assert ("surveys", "0062_apply_default_language_relabel") in migration.dependencies
    assert migration.operations[0].reverse_code is migrations.RunPython.noop


def test_a_deleted_shared_curriculum_is_not_shown():
    shared = _survey()
    _collection(shared)
    _collection(shared)
    Survey.objects.filter(pk=shared.pk).update(deleted_at=now())

    found = rule_report.find()

    assert found.all.shared_curricula == [shared.id]
    assert found.shown.shared_curricula == []


def test_a_blank_type_gets_a_readable_label():
    _collection(_survey(""))

    assert rule_report.find().all.not_curricula == {rule_report.NO_TYPE: 1}


def test_long_id_lists_are_split_across_lines():
    ids = list(range(1, rule_report.IDS_PER_LINE + 3))
    found = rule_report.Found(all=rule_report.Scope(shared_curricula=ids), shown=rule_report.Scope())

    lines = [line for line in rule_report.summary(found) if "shared curricula ids" in line]

    assert len(lines) == 2
    assert lines[1] == f"all: shared curricula ids: {ids[-2]}, {ids[-1]}"
