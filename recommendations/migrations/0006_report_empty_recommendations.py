"""Report the empty recommendations the old "Add recommendation" button saved (intake report #133,
story add-recommendation 2.1).

Report only: it writes nothing. It prints the total of live recommendations with no text in any
language, how many have no translation row and how many only blank ones, how many blank ones still hold an
image, video or embed, the count per survey, the count with no survey, and how many live learner
copies (`UserRecommendation.origin_id`) point at one. Read it from the forms migrate job's output in Loki, `{namespace="itqadem",service_name="forms"}`.
The apply, which soft-deletes them (story 2.2), ships separately in its own release. Never delete
this migration once it has run.

Reverse: nothing to undo.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from recommendations import empty_cleanup

    print("\n  empty-recommendations: report (nothing written)")
    for line in empty_cleanup.summary(empty_cleanup.find_empty()):
        print(f"  empty-recommendations: {line}")


class Migration(migrations.Migration):
    dependencies = [
        ("recommendations", "0005_recommendable_replace_generic_fk"),
        ("surveys", "0060_apply_search_backfill"),
        ("user_surveys", "0033_report_exam_regrade_again"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
