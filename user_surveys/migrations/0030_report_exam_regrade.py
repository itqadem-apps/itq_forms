"""Report what regrading exam grades as score / max_score would change (`forms:AD-10`, `estate:AD-20`).

Report release: it writes nothing. For each learner's first submitted attempt per survey (the one
courses recorded, scored or not), it compares the old grade, the raw score clamped to 0..100, with
score / max_score under the attempt's basis, and prints per survey: candidates (first attempts that
are scored), how many grades would change, how many scored over 100 points, how many have no
positive max, how many first attempts carry no score, and how many candidates were manually
evaluated (courses stored 100 for those). Survey ids and counts only. Every line starts with
`exam_regrade_report`; a forms `survey=<id>` is the courses report's `source_id`. Read it from the
forms migrate job's output in Loki, `{namespace="itqadem",service_name="forms"}`. The apply, a
regrade event courses consumes, ships in the next release (`forms:AD-14`). Never delete this
migration once it has run.

Reverse: nothing to undo.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from user_surveys import regrade_report

    print(f"{regrade_report.TAG} start (nothing written)", flush=True)
    for line in regrade_report.describe(regrade_report.plan()):
        print(line, flush=True)


class Migration(migrations.Migration):
    dependencies = [
        ("user_surveys", "0029_score_basis"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
