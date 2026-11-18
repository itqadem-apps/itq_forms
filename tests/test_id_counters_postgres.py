"""The id-counter read against real Postgres sequences (intake report #133, story
add-recommendation 3.1): rows at explicit ids above a counter are flagged, an in-step table is not,
reading changes no sequence, and the apply (story 3.2) raises only the
counters still behind, never lowering one.

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
from surveys.id_counters import Counter
from tests.test_id_counters import APPLY, MIGRATION, _loader

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


@pytest.fixture(autouse=True)
def _restore_sequences(db):
    """setval and nextval survive the test's rollback; put every sequence back afterwards."""
    saved = _sequences()
    yield
    with connection.cursor() as cur:
        for name, last_value, is_called in saved:
            cur.execute("select setval(%s, %s, %s)", [name, last_value, is_called])


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


def _apply(apps=live_apps):
    return id_counters.raise_behind(apps, connection)


def _state(table):
    return next(c for c in id_counters.read_counters(live_apps, connection) if c.table == table)


def _setval(table, value, is_called):
    with connection.cursor() as cur:
        cur.execute("select pg_get_serial_sequence(%s, 'id')", [table])
        cur.execute("select setval(%s, %s, %s)", [cur.fetchone()[0], value, is_called])


def test_raise_behind_raises_only_the_behind_table(behind_and_in_step):
    before_rows = _rows()
    before = {name: (last, called) for name, last, called in _sequences()}
    rec_before = _state("recommendations_recommendation").next_id

    raised = _apply()

    assert raised == [("recommendations_recommendation", rec_before, behind_and_in_step + 1)]
    rec = _state("recommendations_recommendation")
    assert rec.next_id == behind_and_in_step + 1
    assert rec.behind == 0
    after = {name: (last, called) for name, last, called in _sequences()}
    changed = {name for name in before if before[name] != after[name]}
    assert len(changed) == 1 and next(iter(changed)).endswith("recommendations_recommendation_id_seq")
    assert _rows() == before_rows
    assert _apply() == []  # re-run raises nothing
    assert {name: (last, called) for name, last, called in _sequences()} == after


def test_raise_behind_never_lowers_a_far_ahead_counter(db):
    Classification.objects.create()
    _setval("classifications_classification", 1_000_000, True)
    before = _sequences()

    assert not any(t == "classifications_classification" for t, *_ in _apply())
    assert _sequences() == before


def test_raise_behind_guard_ignores_a_stale_pre_read(db, monkeypatch):
    row = Classification.objects.create()
    _setval("classifications_classification", 1_000_000, True)
    live = {c.table: c for c in id_counters.read_counters(live_apps, connection)}
    stale = Counter("classifications_classification", live["classifications_classification"].sequence, 1, False, row.id)
    assert stale.behind  # the pre-read claims next <= max(id)
    monkeypatch.setattr(id_counters, "read_counters", lambda apps, conn: [stale])
    before = _sequences()

    assert id_counters.raise_behind(live_apps, connection) == []
    assert _sequences() == before


def test_raise_behind_leaves_a_fresh_empty_table(db):
    Classification._base_manager.all().delete()
    _setval("classifications_classification", 1, False)
    before = _sequences()

    _apply()

    assert _sequences() == before
    assert _state("classifications_classification").next_id == 1


def test_raise_behind_raises_an_uncalled_counter_at_max(db):
    top = Classification._base_manager.order_by("-id").values_list("id", flat=True).first() or 0
    Classification.objects.create(id=top + 7)
    _setval("classifications_classification", top + 7, False)

    raised = dict((t, (b, a)) for t, b, a in _apply())

    assert raised["classifications_classification"] == (top + 7, top + 8)
    assert _state("classifications_classification").next_id == top + 8


def test_apply_migration_forwards_prints_raises_and_after_state(behind_and_in_step, capsys):
    apps = _loader().project_state(APPLY).apps
    rows = _rows()

    with connection.schema_editor() as editor:
        importlib.import_module("surveys.migrations.0064_apply_id_counters").forwards(apps, editor)

    assert _rows() == rows
    out = [line.strip() for line in capsys.readouterr().out.splitlines() if line.strip()]
    total = len(id_counters.serial_tables(apps))
    assert out[0] == "id-counters: apply"
    raised = [line for line in out if line.startswith("id-counters: raised ") and "->" in line]
    assert "id-counters: raised recommendations_recommendation: next" in raised[0]
    assert raised[0].endswith(f"-> {behind_and_in_step + 1}")
    i = out.index(f"id-counters: raised: {len(raised)} of {total} table(s)")
    assert out[i + 1] == "id-counters: after:"
    assert len(out[i + 2 :]) == total + 1
    assert out[-1] == f"id-counters: behind: 0 of {total} table(s)"
