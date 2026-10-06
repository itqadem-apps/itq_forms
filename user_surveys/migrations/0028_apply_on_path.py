"""Apply story survey-flow 2.3's on_path backfill (`forms:AD-14`, `forms:AD-17`).

Release B: the write that 0027 reported in release A. For every open attempt whose snapshot
carries a go_to or terminate option, it runs the walk over the stored answers and turns `on_path`
false on the questions the walk does not reach. Every other row keeps 0026's true, which is right
for an attempt with no edge (`forms:AD-16`). Submitted attempts are not walked.

The set it walks is chosen exactly as 0027 chose it, and it prints the same lines, so this
release's log can be read against release A's report.

Reverse: sets `on_path` back to true on the same attempts, the state 0026 left them in.
"""

from django.db import migrations

from user_surveys.flow import walk_snapshot


def _attempts(apps):
    UserSurvey = apps.get_model("user_surveys", "UserSurvey")
    UserAnswerOption = apps.get_model("user_surveys", "UserAnswerOption")
    routed = (
        UserAnswerOption.objects.exclude(flow_action="fall_through")
        .values_list("user_survey_id", flat=True)
        .distinct()
    )
    return UserSurvey.objects.filter(submitted_at__isnull=True, pk__in=routed).order_by("pk")


def forwards(apps, schema_editor):
    UserQuestion = apps.get_model("user_surveys", "UserQuestion")
    UserAnswer = apps.get_model("user_surveys", "UserAnswer")

    attempts = _attempts(apps)
    changed = 0
    flags = 0
    print("\n  on_path backfill, apply:")
    for us in attempts:
        path = walk_snapshot(us, UserQuestion, UserAnswer).path
        snapshot = UserQuestion.objects.filter(user_survey=us)
        snapshot.filter(pk__in=path).update(on_path=True)
        off = snapshot.exclude(pk__in=path).update(on_path=False)
        if off:
            print(f"  user_survey {us.pk}: {off} questions off path")
            changed += 1
            flags += off
    print(
        f"  summary: {attempts.count()} open attempts carry an edge, {changed} changed, "
        f"{flags} flags turned false"
    )


def backwards(apps, schema_editor):
    UserQuestion = apps.get_model("user_surveys", "UserQuestion")
    UserQuestion.objects.filter(user_survey__in=_attempts(apps)).update(on_path=True)


class Migration(migrations.Migration):
    dependencies = [
        ("user_surveys", "0027_report_on_path"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
