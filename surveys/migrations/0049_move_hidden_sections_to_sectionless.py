"""Move the hidden sections' questions to sectionless (story survey-flow 1.5; `forms:AD-9`,
`forms:AD-14`).

Release R3b, the second of `forms:AD-14`'s two ordered learner-data migrations. It ships only
after 0048's dry-run output in the R3a deploy log has been reviewed.

Forward
    Runs `surveys.hidden_section_move.run(apply=True)`: every question under a live hidden section
    moves to `section=null`, together with its `AnswerSchema.section` and its options'
    `AnswerSchemaOption.section`. No `Section` row is deleted, so nothing cascades; the emptied
    sections rank after the others. Each moved question keeps its survey-wide position, and a
    survey is written only if its rendered order is identical before and after. Learner snapshots
    are not touched (`forms:AD-2`). Each survey is its own transaction (`atomic = False`); if any
    is refused the migration fails after writing all the others, so the release stops, and a
    re-run moves only what is left.

Reverse (reversible)
    A moved question no longer names its section, so the rows alone cannot be restored. The record
    is the R3a deploy log: 0048 printed every hidden section with the ids of the questions under
    it, which is exactly the assignment to restore. `manage.py migrate surveys 0048` runs this
    reverse as a no-op; restoring means re-pointing those ids (and their schemas and options) to
    the logged section. A rollback rarely needs it: the rendered order is identical either way,
    and the previous image already reads sectionless questions (story 1.3) and ignores
    `is_hidden` (story 1.4).
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from surveys import hidden_section_move

    counts = hidden_section_move.run(apply=True)
    print(
        f"\n  hidden-section move: {counts['surveys']} surveys, {counts['hidden_sections']} hidden sections, "
        f"{counts['questions_moved']} questions moved, {counts['fully_hidden_surveys']} fully hidden, "
        f"{counts['surveys_refused']} refused"
    )
    if counts["refused"]:
        raise RuntimeError(
            f"{len(counts['refused'])} survey(s) refused, every other survey was written: "
            + "; ".join(counts["refused"][:20])
        )


def backwards(apps, schema_editor):
    """No data to undo here — see the module docstring for the logged reversal."""


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("surveys", "0048_report_hidden_section_move"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
