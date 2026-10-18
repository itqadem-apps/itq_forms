"""Story search-indexes-assessments 1.2 — the search backfill replays live published surveys
(report #102): 0059 reports the count, 0060 writes the events."""

import importlib
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.db.migrations.loader import MigrationLoader
from django.test import override_settings
from django.utils import timezone
from unimessaging.outbox_django.models import OutboxRecord

from conftest import ORG
from survey_collections.models import SurveyCollection
from surveys.models import Survey

REPORT = "surveys.migrations.0059_report_search_backfill"
APPLY = "surveys.migrations.0060_apply_search_backfill"


def _clone(**fields):
    return Survey.objects.create(organization_id=ORG, primary_language="en", **fields)


def _rows():
    return set(OutboxRecord.objects.values_list("id", flat=True))


def _run(module, capsys):
    importlib.import_module(module).forwards(None, None)
    return capsys.readouterr().out


@pytest.fixture
def world(db):
    live = [_clone(status=Survey.STATUS_PUBLISHED) for _ in range(2)]
    deleted = _clone(status=Survey.STATUS_PUBLISHED, deleted_at=timezone.now())
    draft = _clone(status=Survey.STATUS_DRAFT)
    collection = SurveyCollection.objects.create(
        organization_id=ORG, status=SurveyCollection.STATUS_PUBLISHED
    )
    return {"live": live, "deleted": deleted, "draft": draft, "collection": collection}


def test_report_counts_live_published_surveys_and_writes_nothing(world, capsys):
    before = _rows()

    out = _run(REPORT, capsys)

    assert "  search-backfill: surveys=2 events=4 skipped=0" in out
    assert _rows() == before


def test_apply_writes_created_and_published_for_live_published_surveys_only(world, capsys):
    before = _rows()

    out = _run(APPLY, capsys)

    assert "  search-backfill: surveys=2 events=4 skipped=0" in out
    new = OutboxRecord.objects.exclude(id__in=before)
    assert sorted(new.values_list("event_type", "aggregate_id")) == sorted(
        (event, str(s.pk))
        for s in world["live"]
        for event in ("SurveyCreated", "SurveyPublished")
    )


def test_without_live_only_the_command_still_includes_soft_deleted_surveys(world):
    buf = StringIO()
    call_command("reconcile_snapshot", "--published-only", "--surveys-only", "--dry-run", stdout=buf)

    assert "[surveys] would emit=6 skipped=0" in buf.getvalue()


def test_live_only_skips_soft_deleted_collections(world):
    SurveyCollection.objects.create(
        organization_id=ORG, status=SurveyCollection.STATUS_PUBLISHED, deleted_at=timezone.now()
    )
    buf = StringIO()
    call_command(
        "reconcile_snapshot", "--published-only", "--collections-only", "--live-only", "--dry-run", stdout=buf
    )

    assert "[collections] would emit=2 skipped=0" in buf.getvalue()


@pytest.mark.parametrize("module", [REPORT, APPLY])
def test_a_missing_count_line_fails_with_the_captured_output(world, module):
    before = _rows()
    migration = importlib.import_module(module)

    def fake(*args, stdout, **kwargs):
        stdout.write("something unexpected\n")

    with patch.object(migration, "call_command", side_effect=fake):
        with pytest.raises(RuntimeError, match="something unexpected"):
            migration.forwards(None, None)
    assert _rows() == before


@pytest.mark.parametrize("module", [REPORT, APPLY])
def test_no_published_surveys_prints_zero_and_writes_nothing(db, module, capsys):
    _clone(status=Survey.STATUS_DRAFT)
    before = _rows()

    out = _run(module, capsys)

    assert "  search-backfill: surveys=0 events=0 skipped=0" in out
    assert _rows() == before


def test_report_and_apply_counts_agree(world, capsys):
    report = _run(REPORT, capsys).strip().splitlines()[-1]
    apply = _run(APPLY, capsys).strip().splitlines()[-1]

    assert report == apply


def test_apply_depends_on_the_report_and_is_atomic():
    # pytest.ini's --no-migrations blanks MIGRATION_MODULES; read the graph from disk.
    with override_settings(MIGRATION_MODULES={}):
        loader = MigrationLoader(None, ignore_no_migrations=True)
    migration = loader.get_migration("surveys", "0060_apply_search_backfill")

    assert ("surveys", "0059_report_search_backfill") in migration.dependencies
    assert migration.atomic is True
