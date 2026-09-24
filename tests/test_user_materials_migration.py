"""0022 and 0023 are executed by `migrate`, not merely imported.

`pytest.ini` passes `--no-migrations`, for reasons that are good and should
stay: `conftest.py` pins the test database to sqlite, and `pricing/0003` renames
a table with Postgres-only raw SQL, so migrating the whole project from zero
fails before any test runs. Tables are built from the models instead.

The cost of that is a blind spot exactly where it hurts most. Until this module
existed, `user_surveys/0022_usermaterial`'s `CreateModel` had never had its DDL
applied on any engine, and `0023_backfill_user_materials` was only ever reached
by `tests/test_action_materials.py` calling `forwards(live_apps, None)` — no
`migrate` ordering, no atomic block, and the *live* registry standing in for the
historical one. First real execution would have been production Postgres on
deploy, and `itq_forms` deploys on push to main.

Why a subprocess, rather than driving `MigrationExecutor` in-process:

* pytest-django's `--no-migrations` blanks `MIGRATION_MODULES` for the whole
  process, so inside the suite the migration graph is empty — there is nothing
  to execute;
* the suite's database is in-memory sqlite already built from the current
  models, so `user_surveys_usermaterial` is present from the first test and
  cannot be created again;
* `forwards` queries through `.objects`, which resolves to the `default` alias,
  so pointing a side connection at a throwaway database would not redirect it.

A child process with its own `DATABASE_NAME` gets around all three at once, and
gets the real `call_command("migrate", ...)` — real dependency ordering, real
atomicity, real historical registry — instead of an imitation of it.

What this does and does not prove. The engine is sqlite, not Postgres, so
backend-generated DDL is not the production DDL; 0022 is a plain `CreateModel`
with no raw SQL, which is the case where that divergence is smallest. It does
prove that the operations are well-formed, that the graph resolves and orders,
that every `apps.get_model` lookup in `forwards` resolves against the registry
the migration actually sees, and that the run-once guard and the no-op
`backwards` behave under a real reverse-and-replay. `pricing/0003` needs no skip
or fake: it is not in the forwards plan for this target at all (nine apps are,
and `pricing` is not among them), so nothing Postgres-only is reached.

This runs by default. `itq_forms` has no CI that runs pytest — `build.yml` tags,
releases and builds, and nothing else — so an opt-in marker here would be a gate
nobody ever opens, which is the situation this module exists to end. It costs
one subprocess (~25s), shared by every test below via a session fixture. Skip it
during a tight loop with `-m "not migrations"`.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests import _user_materials_migration_run as runner

pytestmark = pytest.mark.migrations

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def migration_report(tmp_path_factory):
    """Apply the migrations once, for real, and return what happened."""
    database = tmp_path_factory.mktemp("user_materials_migration") / "db.sqlite3"

    env = dict(os.environ)
    # The child is not started from the project root's `sys.path`, and the
    # suite may itself be running with an unpacked wheel prepended — hand over
    # whatever this process resolved imports with.
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)

    completed = subprocess.run(
        [sys.executable, runner.__file__, str(database)],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, (
        f"migrate failed\n--- stdout ---\n{completed.stdout}\n"
        f"--- stderr ---\n{completed.stderr}"
    )
    marker = runner.REPORT_MARKER
    assert marker in completed.stdout, f"no report emitted\n{completed.stdout}"
    return json.loads(completed.stdout.split(marker, 1)[1].strip().splitlines()[0])


# ── 0022: the table is really created ────────────────────────────────

def test_the_table_does_not_exist_before_0022(migration_report):
    """Otherwise everything below would pass against a table someone else made."""
    assert migration_report["table_before"] is False


def test_0022_creates_the_table_with_every_field(migration_report):
    assert migration_report["table_after"] is True
    assert migration_report["columns"] == [
        "data",
        "id",
        "origin_id",
        "recommendable_id",
        "source_id",
        "source_model",
        "source_service",
        "user_action_id",
        "user_survey_id",
    ]


def test_0022_indexes_origin_id(migration_report):
    """`db_index=True` on the model has to become an index in the DDL.

    The backfill's own scan filters on `origin_id__in`, and so does every later
    lookup from a UserAction to its materials.
    """
    assert "origin_id" in migration_report["indexed_columns"]


# ── 0023: the backfill runs under `migrate` ──────────────────────────

def test_the_backfill_writes_the_pre_migration_enrolment(migration_report):
    """A band with a pinned material reaches the learner who predates the table."""
    rows = migration_report["rows"]
    seeded = migration_report["seeded"]
    assert len(rows) == 1
    row = rows[0]
    assert row["user_action_id"] == seeded["matched_user_action_id"]
    assert row["user_survey_id"] == seeded["user_survey_id"]
    assert row["source_service"] == "courses"
    assert row["source_model"] == "Course"
    assert row["source_id"] == "101"
    assert row["data"] == {"title": "Intro to Statistics", "slug": "course-101"}
    assert row["recommendable_id"] is not None


def test_the_backfill_skips_a_user_action_whose_action_is_gone(migration_report):
    """`Action` is hard-deleted, so `origin_id` dangles. Skip, do not fail.

    The seed plants a UserAction pointing at an id no Action carries; the run
    completing at all is half the assertion, and writing nothing for it is the
    other half.
    """
    orphan = migration_report["seeded"]["orphan_user_action_id"]
    assert not [r for r in migration_report["rows"] if r["user_action_id"] == orphan]


# ── Reverse and replay ───────────────────────────────────────────────

def test_reversing_to_0022_keeps_the_table_and_its_rows(migration_report):
    """`backwards` is a no-op and 0022 is not reversed, so nothing is lost.

    Nothing on a row says whether the backfill or the enrolment snapshot wrote
    it, so deleting here would take every material a learner has been given
    since deploy — and reversing this migration does not drop the table, so it
    would not come back.
    """
    assert migration_report["table_after_reverse"] is True
    assert migration_report["rows_after_reverse"] == migration_report["rows"]


def test_replaying_the_backfill_cannot_hand_out_a_later_pinning(migration_report):
    """The freeze rule survives a real rollback-and-replay.

    The seed gives the learner a band with nothing pinned to it, and between
    the reversal and the replay the runner pins one. A guard keyed on "which
    user_actions already have rows" never covers that band — it wrote none — so
    a replay would hand the learner a pinning that postdates their enrolment.
    The whole-table guard makes the replay a no-op instead.
    """
    barren = migration_report["seeded"]["barren_user_action_id"]
    assert not [r for r in migration_report["rows"] if r["user_action_id"] == barren]
    assert migration_report["rows_after_replay"] == migration_report["rows"]
