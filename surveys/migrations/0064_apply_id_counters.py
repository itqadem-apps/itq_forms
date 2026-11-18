"""Raise the forms id counters that are behind their tables (intake report #133, story
add-recommendation 3.2).

Apply: at run time it re-reads every forms table's counter (`id_counters.read_counters`) and, for
each one still behind, raises it to the table's live `max(id)` in one guarded statement, so the next
id is `max(id) + 1`. It never lowers a counter and never touches a row. It prints each raise, the
total, then the after-state as the full report. Read it from the forms migrate job's output in Loki,
`{namespace="itqadem",service_name="forms"} |= "id-counters:"`.

Expected on prod (story 3.1's report, 2026-11-18): `raised recommendations_recommendation: next
<~112> -> 12917`, `raised: 1 of 33 table(s)`, and an after-state ending `behind: 0 of 33 table(s)`.

Reverse: nothing to undo; a raised counter is never moved back (`setval` is not transactional).
"""

from django.db import migrations

PREFIX = "  id-counters: "


def forwards(apps, schema_editor):
    from surveys import id_counters

    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        print(f"\n{PREFIX}skipped: {connection.vendor} has no sequences")
        return
    print(f"\n{PREFIX}apply")
    raised = id_counters.raise_behind(apps, connection)
    for table, before, after in raised:
        print(f"{PREFIX}raised {table}: next {before} -> {after}")
    print(f"{PREFIX}raised: {len(raised)} of {len(id_counters.serial_tables(apps))} table(s)")
    print(f"{PREFIX}after:")
    for line in id_counters.summary(id_counters.read_counters(apps, connection)):
        print(f"{PREFIX}{line}")


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0063_report_id_counters"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
