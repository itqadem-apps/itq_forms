"""Report what story survey-flow 1.5's hidden-section move would do (`forms:AD-9`, `forms:AD-14`).

Release R3a: the dry run, delivered through the deploy log instead of a cluster command. It
writes nothing. For every survey holding a live hidden section it prints the hidden sections, the
questions under each, whether the survey is fully hidden, and whether the move would be refused.
The move itself ships in the next migration, in its own release (R3b), after this output is
reviewed.

Reverse: nothing to undo.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from surveys import hidden_section_move

    lines = []
    counts = hidden_section_move.run(apply=False, report=lambda plan: lines.extend(hidden_section_move.describe(plan)))
    print("\n  hidden-section move, dry run (nothing written):")
    for line in lines:
        print(f"  {line}")
    print(
        f"  summary: {counts['surveys']} surveys, {counts['hidden_sections']} hidden sections, "
        f"{counts['questions_moved']} questions to move, {counts['fully_hidden_surveys']} fully hidden, "
        f"{counts['surveys_refused']} refused"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0047_backfill_survey_wide_order"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
