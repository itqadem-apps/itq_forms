"""Report the exam regrade again, before its apply (`estate:AD-20`, `estate:AD-31`).

Report release: it writes nothing. `0030` printed this on 2026-10-07; this prints it afresh so it
is read in Loki next to the release it gates. Same lines as `0030` (tag `exam_regrade_report`),
then `exam_regrade_report would_publish=<n>`: how many first attempts the apply will re-publish
as `SurveyResponseEvaluated` (a grade that changes under score / max_score, or a hand-marked
attempt, which courses stored as 100). Read it from the forms migrate job's output in Loki,
`{namespace="itqadem",service_name="forms"}`. The apply ships in the next release. Never delete
this migration once it has run.

Reverse: nothing to undo.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from user_surveys import regrade_report

    print(f"{regrade_report.TAG} start again (nothing written)", flush=True)
    for line in regrade_report.describe(regrade_report.plan()):
        print(line, flush=True)
    print(f"{regrade_report.TAG} would_publish={len(regrade_report.to_publish())}", flush=True)


class Migration(migrations.Migration):
    dependencies = [
        ("user_surveys", "0032_useranswer_file_asset_id"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
