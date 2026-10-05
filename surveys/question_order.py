"""The one flat order a survey's (or a learner snapshot's) questions are read in.

Shared by the author tree and the learner snapshot (`forms:AD-18`): both models carry
`section` (nullable), `section.order` and `order`.

The default is the legacy key `(section.order nulls last, order nulls last, id)` — what
`Meta.ordering` produces on Postgres today. It is departed from in one case only: the set holds
a sectionless question, every `order` is present and unique, and ordering by `(order, id)` keeps
the sectioned questions in exactly their legacy relative order without splitting any section's
run. Then the orders are survey-wide (`forms:AD-4`) and the only difference is where the
sectionless questions sit, so they sit where their `order` puts them — between sections — instead
of after every section.

Before story 1.6's backfill a multi-section set does not reach that case: section-scoped orders
collide, and a shuffled snapshot interleaves its sections, which fails the relative-order check.
A single-section set can, and then its sectionless question sits by its own `order` (before the
section only if that order is below the section's first). A set with no sectionless question
always gets the legacy key, so its output is unchanged.
"""

from django.db.models import Case, IntegerField, QuerySet, Value, When


def flat_question_ids(questions: QuerySet) -> list[int]:
    rows = list(questions.order_by().values_list("id", "section_id", "section__order", "order"))

    legacy = sorted(
        rows,
        key=lambda r: (r[2] is None, r[2] or 0, r[3] is None, r[3] or 0, r[0]),
    )
    legacy_ids = [r[0] for r in legacy]
    if all(r[1] is not None for r in rows):
        return legacy_ids

    orders = [r[3] for r in rows]
    if None in orders or len(set(orders)) != len(orders):
        return legacy_ids

    wide = sorted(rows, key=lambda r: (r[3], r[0]))
    if [r[0] for r in wide if r[1] is not None] != [r[0] for r in legacy if r[1] is not None]:
        return legacy_ids
    # A sectionless question inside a section's run would split it (`forms:AD-4`).
    runs = [r[1] for r in wide]
    starts = [s for i, s in enumerate(runs) if s is not None and (i == 0 or runs[i - 1] != s)]
    if len(starts) != len(set(starts)):
        return legacy_ids
    return [r[0] for r in wide]


def in_flat_order(questions: QuerySet) -> QuerySet:
    """`questions` ordered by `flat_question_ids`, still a QuerySet so the GraphQL optimizer
    can prefetch beneath it."""
    ids = flat_question_ids(questions)
    if not ids:
        return questions.none()
    position = Case(
        *(When(id=pk, then=Value(i)) for i, pk in enumerate(ids)),
        output_field=IntegerField(),
    )
    return questions.order_by(position, "id")
