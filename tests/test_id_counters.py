"""The id-counter report lists every serial-id forms table, flags the ones whose counter would hand
out an id that already exists, and writes nothing (intake report #133, story add-recommendation
3.1); story 3.2 raises them through the same read."""

import importlib

import pytest
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.test import override_settings

from recommendations.models import Recommendation
from surveys import id_counters
from surveys.id_counters import Counter

MIGRATION = ("surveys", "0063_report_id_counters")


def _loader():
    # pytest.ini's --no-migrations blanks MIGRATION_MODULES; read the graph from disk.
    with override_settings(MIGRATION_MODULES={}):
        return MigrationLoader(None, ignore_no_migrations=True)


def test_serial_tables_from_the_historical_registry():
    apps = _loader().project_state(MIGRATION).apps

    tables = dict(id_counters.serial_tables(apps))

    assert tables["recommendations_recommendation"] == "id"
    for m2m in ("accounts_user_groups", "accounts_user_user_permissions", "user_surveys_useranswer_selected_options"):
        assert m2m in tables
    assert "accounts_user" not in tables  # char id
    assert not any(t.startswith(("taxonomy_", "media_")) for t in tables)  # UUID ids
    assert not any(t.startswith(("auth_", "django_")) for t in tables)
    assert list(tables) == sorted(tables)


def test_summary_formats_every_case():
    counters = [
        Counter("a_behind", '"a_behind_id_seq"', 111, True, 12916),
        Counter("b_in_step", '"b_in_step_id_seq"', 50, True, 50),
        Counter("c_fresh", '"c_fresh_id_seq"', 1, False, None),
        Counter("d_unc_at_max", '"d_unc_at_max_id_seq"', 7, False, 7),
        Counter("e_no_seq", None),
    ]

    lines = id_counters.summary(counters)

    assert lines == [
        "a_behind: last_value=111 is_called=True next=112 max(id)=12916 BEHIND by 12805",
        "b_in_step: last_value=50 is_called=True next=51 max(id)=50",
        "c_fresh: last_value=1 is_called=False next=1 max(id)=none",
        "d_unc_at_max: last_value=7 is_called=False next=7 max(id)=7 BEHIND by 1",
        "e_no_seq: no sequence",
        "behind: 2 of 5 table(s)",
    ]


@pytest.mark.skipif(connection.vendor == "postgresql", reason="Postgres path: test_id_counters_postgres.py")
def test_forwards_on_sqlite_only_skips(db, capsys):
    Recommendation.objects.create()
    before = sorted(Recommendation._base_manager.values_list("id", "survey_id", "deleted_at"))

    class Editor:
        pass

    editor = Editor()
    editor.connection = connection
    importlib.import_module("surveys.migrations.0063_report_id_counters").forwards(None, editor)

    assert sorted(Recommendation._base_manager.values_list("id", "survey_id", "deleted_at")) == before
    out = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert out == [f"  id-counters: skipped: {connection.vendor} has no sequences"]


def test_report_sits_on_every_leaf():
    loader = _loader()
    migration = loader.get_migration(*MIGRATION)

    assert loader.graph.leaf_nodes("surveys") == [MIGRATION]
    for label in id_counters.PROJECT_APPS:
        if label == "surveys":
            continue
        (leaf,) = loader.graph.leaf_nodes(label)
        assert leaf in migration.dependencies


def test_serial_tables_skips_an_app_the_registry_lacks():
    class Registry:
        def get_app_config(self, label):
            raise LookupError(label)

    assert id_counters.serial_tables(Registry()) == []
