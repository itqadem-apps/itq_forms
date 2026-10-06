"""Report what story autism-merge 1.1 would move (report #64, `estate:AD-20`).

Report release: it writes nothing. It prints every projected category named التوحد (id, tree, path,
tombstoned, children), the live اضطراب طيف التوحد target in the same tree, and the count and ids of
surveys and survey collections on each. Read it from the forms migrate job's output in Loki,
`{namespace="itqadem",service_name="forms"}`. The apply ships in the next release, built from those
ids. Never delete this migration once it has run.

Reverse: nothing to undo.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from surveys import autism_merge

    print("\n  autism-merge report (nothing written):")
    for line in autism_merge.describe(autism_merge.plan()):
        print(f"  autism-merge: {line}")


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0052_score_basis"),
        ("survey_collections", "0015_organization_id_required"),
        ("taxonomy", "0004_deferredcategoryevent_category_deleted_at_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
