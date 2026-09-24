"""Apply ``user_surveys`` 0022 and 0023 for real, on a throwaway sqlite database.

Run as a subprocess by ``tests/test_user_materials_migration.py`` — that module
explains why this cannot run inside the pytest process. It is also runnable by
hand:

    DJANGO_SECRET_KEY=x python tests/_user_materials_migration_run.py /tmp/m.sqlite3

Everything observed is emitted as one JSON object after ``REPORT_MARKER`` so
that Django's own chatter on stdout can never be mistaken for the report. This
file makes no assertions; the calling test owns those, so a failure reads as a
named expectation rather than as a subprocess exit code.

The filename is underscore-prefixed on purpose: ``pytest.ini``'s
``python_files`` would otherwise collect it, and importing it inside the suite
is precisely what it exists to avoid.
"""

import json
import os
import sys

REPORT_MARKER = "---USER-MATERIALS-MIGRATION-REPORT---"

# The state 0022 builds on. Both are named explicitly: 0021 is where
# `user_surveys` sits before the table exists, and `recommendations` 0005 is
# 0022's other dependency, so the seed below needs it applied to have
# `Material` and `Recommendable` tables to write into.
BEFORE = [
    ("recommendations", "0005_recommendable_replace_generic_fk"),
    ("user_surveys", "0021_rename_survey_types"),
]
AFTER = ("user_surveys", "0023_backfill_user_materials")
TABLE = "user_surveys_usermaterial"

# An origin_id no Action carries. `Action` is hard-deleted and cascades with
# its `Survey`, so in production a share of UserAction rows point at nothing;
# the backfill must skip those rather than fail the deploy.
DANGLING_ORIGIN_ID = 9_999_999


def _configure(database_path):
    os.environ["DJANGO_SETTINGS_MODULE"] = "app.settings"
    # settings.py prefers DATABASE_URL when it is set, which would send this
    # run at whatever database the shell happens to point to.
    os.environ.pop("DATABASE_URL", None)
    os.environ.pop("ACL_DATABASE_URL", None)
    os.environ["DATABASE_ENGINE"] = "django.db.backends.sqlite3"
    os.environ["DATABASE_NAME"] = database_path
    os.environ.setdefault("DJANGO_SECRET_KEY", "migration-test-only-not-a-real-key")

    import django

    django.setup()


def _table_names():
    from django.db import connection

    return set(connection.introspection.table_names())


def _columns():
    from django.db import connection

    with connection.cursor() as cursor:
        return sorted(
            c.name for c in connection.introspection.get_table_description(cursor, TABLE)
        )


def _indexed_columns():
    """Columns the real DDL put an index on, as a flat set.

    `origin_id` carries `db_index=True`; nothing in the suite has ever checked
    that the generated DDL actually creates it.
    """
    from django.db import connection

    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, TABLE)
    indexed = set()
    for details in constraints.values():
        if details.get("index"):
            indexed.update(details["columns"])
    return sorted(indexed)


def _historical(targets):
    """The app registry as a migration standing at `targets` would see it.

    This is the registry `apps.get_model` reads inside `forwards`, rather than
    the live one the fast semantic tests stand in with.
    """
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    return MigrationExecutor(connection).loader.project_state(targets, at_end=True).apps


def _seed():
    """Write the enrolment rows a pre-0022 deploy would have left behind."""
    apps = _historical(BEFORE)
    Survey = apps.get_model("surveys", "Survey")
    Action = apps.get_model("recommendations", "Action")
    Material = apps.get_model("recommendations", "Material")
    Recommendable = apps.get_model("recommendations", "Recommendable")
    UserSurvey = apps.get_model("user_surveys", "UserSurvey")
    UserAction = apps.get_model("user_surveys", "UserAction")

    survey = Survey.objects.create()
    band = Action.objects.create(survey=survey, lower_limit=0, upper_limit=100)
    recommendable = Recommendable.objects.create(
        source_service="courses",
        source_model="Course",
        source_id="101",
        data={"title": "Intro to Statistics", "slug": "course-101"},
    )
    Material.objects.create(action=band, recommendable=recommendable)

    # A second band with nothing pinned to it. This is the case that makes the
    # replay check below discriminating: a guard keyed on "which user_actions
    # already have rows" leaves this one out of that set forever, so a replay
    # would backfill it from whatever an admin pinned in the meantime.
    barren_band = Action.objects.create(survey=survey, lower_limit=0, upper_limit=50)

    user_survey = UserSurvey.objects.create()
    matched = UserAction.objects.create(
        user_survey=user_survey, origin_id=band.id, lower_limit=0, upper_limit=100
    )
    barren = UserAction.objects.create(
        user_survey=user_survey, origin_id=barren_band.id, lower_limit=0, upper_limit=50
    )
    orphan = UserAction.objects.create(
        user_survey=user_survey, origin_id=DANGLING_ORIGIN_ID
    )
    return {
        "band_id": band.id,
        "barren_band_id": barren_band.id,
        "user_survey_id": user_survey.id,
        "matched_user_action_id": matched.id,
        "barren_user_action_id": barren.id,
        "orphan_user_action_id": orphan.id,
    }


def _rows():
    """Every UserMaterial row, read through the post-0023 historical registry."""
    UserMaterial = _historical([AFTER]).get_model("user_surveys", "UserMaterial")
    return [
        {
            "origin_id": row.origin_id,
            "user_survey_id": row.user_survey_id,
            "user_action_id": row.user_action_id,
            "recommendable_id": row.recommendable_id,
            "source_service": row.source_service,
            "source_model": row.source_model,
            "source_id": row.source_id,
            "data": row.data,
        }
        for row in UserMaterial.objects.order_by("id")
    ]


def _pin_another_material(band_id):
    """An admin pins an entry to the barren band after the backfill has run.

    The learner enrolled when that band had nothing on it, so the freeze rule
    says they never see this. The whole-table guard in `forwards` holds that
    line through a reverse-and-replay; a guard keyed on which user_actions
    already have rows would not, because a band that pinned nothing at
    enrolment is absent from that set.
    """
    apps = _historical([AFTER])
    Action = apps.get_model("recommendations", "Action")
    Material = apps.get_model("recommendations", "Material")
    Recommendable = apps.get_model("recommendations", "Recommendable")

    Material.objects.create(
        action=Action.objects.get(id=band_id),
        recommendable=Recommendable.objects.create(
            source_service="courses",
            source_model="Course",
            source_id="777",
            data={"title": "Pinned Later", "slug": "course-777"},
        ),
    )


def main(database_path):
    _configure(database_path)

    from django.core.management import call_command

    report = {}

    for app_label, target in BEFORE:
        call_command("migrate", app_label, target, verbosity=0)
    report["table_before"] = TABLE in _table_names()
    report["seeded"] = _seed()

    # The real thing: 0022's CreateModel DDL and 0023's RunPython, applied by
    # `migrate` in dependency order, inside the atomic block Django wraps them
    # in — none of which the default suite reaches.
    call_command("migrate", *AFTER, verbosity=0)
    report["table_after"] = TABLE in _table_names()
    report["columns"] = _columns()
    report["indexed_columns"] = _indexed_columns()
    report["rows"] = _rows()

    _pin_another_material(report["seeded"]["barren_band_id"])

    # `backwards` is a deliberate no-op and 0022 is NOT reversed here, so the
    # table survives and so must its rows.
    call_command("migrate", "user_surveys", "0022_usermaterial", verbosity=0)
    report["table_after_reverse"] = TABLE in _table_names()
    report["rows_after_reverse"] = _rows()

    # Replay. The guard keys on the whole table being empty, so this is a
    # no-op — including for the entry pinned above.
    call_command("migrate", *AFTER, verbosity=0)
    report["rows_after_replay"] = _rows()

    print(REPORT_MARKER)
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
