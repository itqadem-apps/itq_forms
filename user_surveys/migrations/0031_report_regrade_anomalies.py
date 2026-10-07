"""Report what explains the exam regrade report's two anomalies (`forms:AD-10`, `estate:AD-20`).

Report release: it writes nothing. It prints, every line starting with `anomaly_report`:
- `first_vs_later survey=182`: submitted attempts on survey 182 split into the learner's first
  (earliest `submitted_at`, then id, as `0030_report_exam_regrade` picks it) and later, each scored
  (`use_score` and a score) or not, plus attempts whose user is gone;
- `max_not_positive survey=<id>`: per survey, the scored first attempts whose `max_scores` is 0
  or less, with how many have a positive score, were manually evaluated, have no snapshot
  questions, have an answer with no question but a selected option, have no option scoring above
  0, and have any option scoring below 0; then a summary.

Survey ids and counts only. Read it from the forms migrate job's output in Loki,
`{namespace="itqadem",service_name="forms"}`. Any fix is ruled after the counts are read, in its
own release (`forms:AD-14`). Never delete this migration once it has run.

Reverse: nothing to undo.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from user_surveys import anomaly_report

    print(f"{anomaly_report.TAG} start (nothing written)", flush=True)
    for line in anomaly_report.describe(anomaly_report.plan_survey_182(), anomaly_report.plan_max_not_positive()):
        print(line, flush=True)


class Migration(migrations.Migration):
    dependencies = [
        ("user_surveys", "0030_report_exam_regrade"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
