"""Report which forms id counters are behind their tables (intake report #133, story
add-recommendation 3.1).

Report only: it writes nothing. For every forms table with an auto-increment id it prints the
sequence's `last_value`, `is_called`, the next id it would hand out and the table's `max(id)`,
flags each table whose next id already exists, and closes with how many are behind. Read it from
the forms migrate job's output in Loki, `{namespace="itqadem",service_name="forms"}`.
The apply, which raises the counters (story 3.2), ships separately in its own release. Never delete
this migration once it has run.

Reverse: nothing to undo.
"""

from django.db import migrations

PREFIX = "  id-counters: "


def forwards(apps, schema_editor):
    from surveys import id_counters

    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        print(f"\n{PREFIX}skipped: {connection.vendor} has no sequences")
        return
    print(f"\n{PREFIX}report (nothing written)")
    for line in id_counters.summary(id_counters.read_counters(apps, connection)):
        print(f"{PREFIX}{line}")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_childguardian"),
        ("surveys", "0062_apply_default_language_relabel"),
        ("taxonomy", "0004_deferredcategoryevent_category_deleted_at_and_more"),
        ("survey_collections", "0019_restore_course_exam_links"),
        ("pricing", "0006_price_currency_egp_constraints"),
        ("classifications", "0003_remove_classification_name"),
        ("recommendations", "0006_report_empty_recommendations"),
        ("external_references", "0001_initial"),
        ("user_surveys", "0033_report_exam_regrade_again"),
        ("media", "0001_upload_records"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
