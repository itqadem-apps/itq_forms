"""Report what story survey-flow 2.3's on_path backfill would do (`forms:AD-14`, `forms:AD-17`).

Release A: the dry run, delivered through the deploy log instead of a cluster command. It writes
nothing. 0026 lands `on_path` true on every row, which is right for any attempt whose snapshot
carries no go_to or terminate option (`forms:AD-16`). For the open attempts that carry one, this
runs the walk over their stored answers and prints how many flags it would turn false. The apply
ships in the next release, after this output is reviewed. Submitted attempts are not walked.

Runs on historical models and the pure walk, so a later change to the real models cannot change
what it reports. Prints ids and counts only, never answers.

Reverse: nothing to undo.
"""

from django.db import migrations

from user_surveys.flow import walk_snapshot


def forwards(apps, schema_editor):
    UserSurvey = apps.get_model("user_surveys", "UserSurvey")
    UserQuestion = apps.get_model("user_surveys", "UserQuestion")
    UserAnswer = apps.get_model("user_surveys", "UserAnswer")
    UserAnswerOption = apps.get_model("user_surveys", "UserAnswerOption")

    routed = (
        UserAnswerOption.objects.exclude(flow_action="fall_through")
        .values_list("user_survey_id", flat=True)
        .distinct()
    )
    attempts = UserSurvey.objects.filter(submitted_at__isnull=True, pk__in=routed).order_by("pk")

    changed = []
    flags = 0
    for us in attempts:
        snapshot = UserQuestion.objects.filter(user_survey=us).count()
        off = snapshot - len(walk_snapshot(us, UserQuestion, UserAnswer).path)
        if off:
            changed.append((us.pk, off))
            flags += off

    print("\n  on_path backfill, dry run (nothing written):")
    for pk, off in changed:
        print(f"  user_survey {pk}: {off} questions off path")
    print(
        f"  summary: {attempts.count()} open attempts carry an edge, {len(changed)} would change, "
        f"{flags} flags would turn false"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("user_surveys", "0026_on_path"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
