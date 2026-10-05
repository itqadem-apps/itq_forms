"""Backfill the survey-wide question order (story survey-flow 1.6; `forms:AD-4`, `forms:AD-14`).

The first of `forms:AD-14`'s two ordered learner-data migrations; it ships in its own release (R2),
before story 1.5's hidden-section move.

Forward
    Runs `surveys.order_backfill.run(apply=True)` — the same code as
    `manage.py backfill_question_order --apply`, whose `--dry-run` must be reviewed against
    production before this ships:

    * every survey is renumbered 1..N through `renumber_questions(survey_id, sequence=...)` with
      the legacy key, and its `Section.order` re-derived by the same call;
    * every open (unsubmitted) learner snapshot is renumbered 1..N by
      `(UserSection.order nulls last, UserQuestion.order, id)`;
    * submitted snapshots are not touched.

    Each survey and snapshot is written in its own transaction (`atomic = False` here), and only
    if its rendered order is identical before and after. If any owner is refused the migration
    fails after writing all the others, so the release stops; resolve the refused surveys (see
    the command's docstring) and re-run — owners already written plan no change.

    Then `Question.Meta.ordering` flips to `["order"]` (state only, no SQL).

    It imports the live models rather than `apps.get_model`, because the story requires the
    author-side order to be reached through `renumber_questions` and no other code path. It reads
    and writes only `id`, `survey_id`, `section_id`, `order` and `Section.order`, which no later
    migration is expected to rename; on an empty database it writes nothing.

Reverse (reversible)
    Data: nothing to undo. Every owner was written only where its rendered order was unchanged,
    and the previous release (itq_forms 363daae) reads survey-wide orders with the legacy key,
    which renders them identically — the same orders it already writes on every author save
    since story 1.2. Rolling back is therefore: redeploy the previous image, then
    `manage.py migrate surveys 0046`, which runs this no-op and restores the old
    `Meta.ordering`. The prior per-row orders are not restored; the reviewed `--dry-run --json`
    output records every row's previous order (`was`) should an exact restore ever be needed.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    from surveys import order_backfill

    counts = order_backfill.run(apply=True)
    print(
        f"\n  surveys: {counts['surveys']} scanned, {counts['surveys_affected']} renumbered; "
        f"open snapshots: {counts['snapshots']} scanned, {counts['snapshots_affected']} renumbered"
    )
    if counts["refused"]:
        raise RuntimeError(
            f"{len(counts['refused'])} owner(s) refused, every other owner was written: "
            + "; ".join(counts["refused"][:20])
            + ". Run `manage.py backfill_question_order --dry-run` for the full list."
        )


def backwards(apps, schema_editor):
    """No data to undo — see the module docstring."""


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("surveys", "0046_answer_schema_section_nullable"),
        ("user_surveys", "0023_backfill_user_materials"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
        migrations.AlterModelOptions(name="question", options={"ordering": ["order"]}),
    ]
