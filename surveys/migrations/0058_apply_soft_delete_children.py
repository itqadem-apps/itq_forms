"""Stamp the live children of already soft-deleted rows (story surveys-builder 3.2,
`forms:AD-21`, `forms:AD-14`).

Release R2. It ships only after 0057's report in the R1 migrate-job log (Loki,
`{namespace="itqadem",service_name="forms"}`) has been read, and before the default managers
switch in R3, whose plain `deleted_at` filter is correct only once no live child sits under a
deleted parent.

Forward
    Runs `surveys.soft_delete_backfill.run(apply=True)`: a live question under a deleted section
    takes the section's `deleted_at`; a live option under a deleted question (or a question under a
    deleted section) takes that question's effective `deleted_at`; a live option whose `go_to`
    names a deleted question becomes fall-through with no target. Each survey is re-planned and
    written in its own transaction under the survey lock (`atomic = False`), so a re-run writes
    only what is left. Learner snapshots are not touched (`forms:AD-2`). Every id written is
    printed to the migrate-job log.

Reverse: irreversible in code
    `backwards` is a no-op: `migrate surveys 0057` leaves every row as this wrote it. Undoing it
    is manual, from the ids this printed: clear `deleted_at` on the stamped questions and options,
    and restore `flow_action` go_to with the logged target on each fall-through option.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from surveys import soft_delete_backfill

    lines = []
    counts = soft_delete_backfill.run(apply=True, report=lambda p: lines.extend(soft_delete_backfill.describe(p)))
    print("\n  soft-delete children, apply:")
    for line in lines:
        print(f"  soft-delete-children: {line}")
    for line in soft_delete_backfill.summary(counts, applied=True):
        print(f"  soft-delete-children: {line}")


def backwards(apps, schema_editor):
    """Irreversible in code; the module docstring gives the manual reversal from the logged ids."""


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("surveys", "0057_report_soft_delete_children"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
