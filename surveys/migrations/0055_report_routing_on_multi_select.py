"""Report the routing options left on questions that cannot route (`forms:AD-3`, `estate:AD-20`).

Report release: it writes nothing. It prints every author answer option that carries a `go_to` or
`terminate` edge while its question or answer schema is not radio or dropdown (survey, question,
deleted flag, option, both types, action, target), and counts only (never ids) the learner-snapshot
options in the same state, split into open and submitted attempts. `full_form` surveys are left
out (`forms:AD-11`). Read it from the forms migrate job's output in Loki,
`{namespace="itqadem",service_name="forms"}`. The apply, which clears those edges to
`fall_through`, ships in the next release, built from those ids (`forms:AD-14`). Never delete this
migration once it has run.

Reverse: nothing to undo.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from surveys import routing_repair

    print("\n  routing-repair report (nothing written):")
    for line in routing_repair.describe(routing_repair.plan()):
        print(f"  routing-repair: {line}")


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0054_apply_autism_merge"),
        ("user_surveys", "0029_score_basis"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
