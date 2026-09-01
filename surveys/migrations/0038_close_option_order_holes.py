"""Close the holes a deleted answer option left behind.

``AnswerSchemaOption`` had no ``post_delete`` resequencing, though ``Section``
and ``Question`` have had one since they were written. Deleting the third of
four choices therefore left the schema holding 1, 2, 4 permanently, and a
respondent saw three choices where the instrument defines four. The signal is
added in ``surveys.models.signals``, but it only governs deletes from here on —
every schema already carrying a hole still carries it, and prod cannot run a
management command. So the sweep runs here, once, on deploy.

Renumbering is safe to do unattended because nothing keys off ``order``:
recorded answers reference options through ``UserAnswer.selected_options``, a
many-to-many on the option id, and every other read is an ``order_by`` for
display. Closing a hole changes the numbering, never which choice is which,
and never which option a respondent picked.

What this does not do, and cannot: bring the deleted choice back. A gap means
an option was destroyed, and only an author or a backup restores it. This
leaves the sequence clean and stops the follow-on defect, where ``save``
assigns ``count() + 1`` and hands a new option an order the survivor already
holds.

Snapshots are deliberately untouched. ``UserAnswerOption`` rows record what a
respondent was actually shown; rewriting them would edit the evidence, and
would not restore the missing choice either.
"""

from collections import defaultdict

from django.db import migrations


def close_holes(apps, schema_editor):
    AnswerSchemaOption = apps.get_model("surveys", "AnswerSchemaOption")

    by_schema = defaultdict(list)
    rows = AnswerSchemaOption.objects.values("id", "schema_id", "order").order_by(
        "order", "id"
    )
    for row in rows.iterator():
        by_schema[row["schema_id"]].append(row)

    repairs = []
    for options in by_schema.values():
        if [o["order"] for o in options] == list(range(1, len(options) + 1)):
            continue
        for index, option in enumerate(options, start=1):
            if option["order"] != index:
                repairs.append((option["id"], index))

    for option_id, order in repairs:
        AnswerSchemaOption.objects.filter(pk=option_id).update(order=order)

    if repairs:
        print(f"  closed option-order holes: {len(repairs)} options resequenced")


class Migration(migrations.Migration):
    dependencies = [("surveys", "0037_add_deleted_at")]

    operations = [
        # Irreversible by nature: the previous numbering was the defect, and
        # nothing records what it was. Reversing is a no-op rather than an
        # error so a rollback of the surrounding migrations is not blocked.
        migrations.RunPython(close_holes, migrations.RunPython.noop),
    ]
