"""Report the live children of already soft-deleted rows (story surveys-builder 3.2,
`forms:AD-21`, `forms:AD-14`).

Report release (R1): it writes nothing. For every survey holding a live question under a deleted
section, or a live option under a deleted question or section, it prints the deleted parent and
the ids it would stamp; each live option whose `go_to` names a deleted question, which the apply
makes fall-through; the count of options whose own section column is stale (left alone); and any
live question with no survey and no section (left alone).
Read it from the forms migrate job's output in Loki, `{namespace="itqadem",service_name="forms"}`.
The apply, which stamps each orphan with its parent's `deleted_at` and clears those edges, ships as 0058 in the next
release (R2), before the default managers switch (R3). Never delete this migration once it has
run.

Reverse: nothing to undo.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from surveys import soft_delete_backfill

    lines = []
    counts = soft_delete_backfill.run(apply=False, report=lambda p: lines.extend(soft_delete_backfill.describe(p)))
    print("\n  soft-delete children, report (nothing written):")
    for line in lines:
        print(f"  soft-delete-children: {line}")
    for line in soft_delete_backfill.summary(counts, applied=False):
        print(f"  soft-delete-children: {line}")


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0056_answerschemaoption_deleted_at"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
