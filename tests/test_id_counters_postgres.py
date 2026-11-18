"""The id-counter read against real Postgres sequences (intake report #133, story
add-recommendation 3.1): rows at explicit ids above a counter are flagged, an in-step table is not,
and reading changes no sequence.

Postgres only: sqlite has no sequences. Run with `DATABASE_URL` pointing at a local Postgres; under
the default sqlite settings every test here is skipped.
"""

import importlib

import pytest
from django.apps import apps as live_apps
from django.db import connection

from classifications.models import Classification
from recommendations.models import Recommendation
from surveys import id_counters
from tests.test_id_counters import MIGRATION, _loader

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(connection.vendor != "postgresql", reason="needs Postgres sequences"),
]


def _sequences():
    """(sequence, last_value, is_called) of every sequence on the search path, read directly."""
    with connection.cursor() as cur:
        cur.execute(
            "select quote_ident(schemaname) || '.' || quote_ident(sequencename) from pg_sequences "
            "where schemaname = any(current_schemas(false)) order by 1"
        )
        names = [row[0] for row in cur.fetchall()]
        state = []
        for name in names:
            cur.execute(f"select last_value, is_called from {name}")
            state.append((name, *cur.fetchone()))
    return state


def _rows():
    return (
        sorted(Recommendation._base_manager.values_list("id", flat=True)),
        sorted(Classification._base_manager.values_list("id", flat=True)),
    )


@pytest.fixture
def behind_and_in_step(db):
    Classification.objects.create()  # takes its id from the counter: in step
    top = Recommendation._base_manager.order_by("-id").values_list("id", flat=True).first() or 0
    Recommendation.objects.create(id=top + 500)
    Recommendation.objects.create(id=top + 900)
    return top + 900


def test_read_counters_flags_the_behind_table_and_writes_nothing(behind_and_in_step):
    before = (_sequences(), _rows())

    counters = {c.table: c for c in id_counters.read_counters(live_apps, connection)}

    assert (_sequences(), _rows()) == before
    rec = counters["recommendations_recommendation"]
    assert rec.sequence
    assert rec.max_id == behind_and_in_step
    assert rec.next_id <= rec.max_id
    assert rec.behind == rec.max_id - rec.next_id + 1 > 0
    cls = counters["classifications_classification"]
    assert cls.sequence and cls.is_called is True
    assert cls.max_id == cls.last_value
    assert cls.behind == 0


def test_migration_forwards_prints_the_report(behind_and_in_step, capsys):
    apps = _loader().project_state(MIGRATION).apps
    before = (_sequences(), _rows())

    with connection.schema_editor() as editor:
        importlib.import_module("surveys.migrations.0063_report_id_counters").forwards(apps, editor)

    assert (_sequences(), _rows()) == before
    out = [line.strip() for line in capsys.readouterr().out.splitlines() if line.strip()]
    total = len(id_counters.serial_tables(apps))
    assert out[0] == "id-counters: report (nothing written)"
    assert len(out) == total + 2
    assert any(
        line.startswith("id-counters: recommendations_recommendation:") and " BEHIND by " in line for line in out
    )
    assert not any(line.startswith("id-counters: classifications_classification:") and "BEHIND" in line for line in out)
    behind = sum("BEHIND by" in line for line in out)
    assert out[-1] == f"id-counters: behind: {behind} of {total} table(s)"
    assert behind >= 1
