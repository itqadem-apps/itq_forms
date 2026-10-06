"""The one flat order a survey's (or a learner snapshot's) questions are read in.

Shared by the author tree and the learner snapshot (`forms:AD-18`): both models carry
`section` (nullable), `section.order` and `order`.

The default is the legacy key `(section.order nulls last, order nulls last, id)` — what
`Meta.ordering` produced on Postgres before story 1.6. It is departed from in one case only: the set holds
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

`renumber_questions` writes the order back as 1..N across the survey (`forms:AD-4`); it is the
only code that assigns `Question.order`, and it derives `Section.order` from it. Since story 1.6
its own key is `(order, id)`, and `Question.Meta.ordering` is `["order"]`; after the backfill the
legacy key and `(order, id)` agree on every survey. The legacy key stays here as the reader's
default because submitted snapshots were never renumbered and still hold section-scoped or
shuffled orders.
"""

from collections.abc import Iterable, Mapping

from django.core.exceptions import ValidationError
from django.db.models import Case, IntegerField, Q, QuerySet, Value, When


def flat_question_ids(questions: QuerySet) -> list[int]:
    return flat_order(list(questions.order_by().values_list("id", "section_id", "section__order", "order")))


def flat_order(rows: list[tuple]) -> list[int]:
    """`flat_question_ids` over `(id, section_id, section_order, order)` rows already in memory, so
    a dry run can ask what an order it has not written would render as."""
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


def live_survey_questions(survey_id) -> QuerySet:
    """The author-side set the admin preview lists and steps through: not soft-deleted, and not
    under a soft-deleted section."""
    from surveys.models import Question

    return Question.objects.filter(survey_id=survey_id, deleted_at__isnull=True).filter(
        Q(section__isnull=True) | Q(section__deleted_at__isnull=True)
    )


def renumber_questions(survey_id, sequence: list[int] | None = None, section_rank: list[int] | None = None) -> list[int]:
    """Assign every question of `survey_id` its survey-wide position 1..N, then rank the sections
    by their first question (`forms:AD-4`). Returns the question ids in their new order.

    Without `sequence` the key is `(order, id)` (story 1.6). On a survey whose orders still
    collide or would split a section — one the backfill has not reached, or rows written around
    this function — it falls back to the legacy key (`flat_question_ids`), so a save can never
    scramble a survey that is not yet survey-wide. A newly
    saved question (`order` null) lands at the end of its section, or of the survey when it has
    none — appended to the order the others already hold, so it cannot unseat a sectionless
    question from between two sections. A reorder passes the
    `sequence` it wants instead; it must name every question of the survey exactly once.

    Sections holding no question go after all others, by `section_rank` (a reorder's request)
    where it names them, then by their prior `order`.
    """
    from surveys.models import Question, Section

    if survey_id is None:
        return []
    questions = Question.objects.filter(survey_id=survey_id)
    rows = {pk: (section_id, order) for pk, section_id, order in questions.order_by().values_list("id", "section_id", "order")}
    if sequence is None:
        sequence = _appended(_placed_order(questions.filter(order__isnull=False)), rows)
    elif len(sequence) != len(rows) or set(sequence) != set(rows):
        raise ValueError("A renumber sequence must name every question of the survey exactly once.")

    renumbered = [Question(pk=pk, order=i) for i, pk in enumerate(sequence, start=1) if rows[pk][1] != i]
    if renumbered:
        Question.objects.bulk_update(renumbered, ["order"])

    first: dict[int, int] = {}
    for i, pk in enumerate(sequence):
        if rows[pk][0] is not None:
            first.setdefault(rows[pk][0], i)
    hint = {sid: i for i, sid in enumerate(section_rank or ())}
    sections = list(Section.objects.filter(survey_id=survey_id).order_by().values_list("id", "order"))
    held = sorted((s for s in sections if s[0] in first), key=lambda s: first[s[0]])
    empty = sorted(
        (s for s in sections if s[0] not in first),
        key=lambda s: (hint.get(s[0], len(hint)), s[1] is None, s[1] or 0, s[0]),
    )
    ranked = [Section(pk=sid, order=i) for i, (sid, order) in enumerate(held + empty, start=1) if order != i]
    if ranked:
        Section.objects.bulk_update(ranked, ["order"])
    return sequence


def _placed_order(questions: QuerySet) -> list[int]:
    rows = list(questions.order_by().values_list("id", "section_id", "section__order", "order"))
    wide = [r[0] for r in sorted(rows, key=lambda r: (r[3], r[0]))]
    if len({r[3] for r in rows}) == len(rows) and not split_sections(wide, {r[0]: r[1] for r in rows}):
        return wide
    return flat_order(rows)


def _appended(sequence: list[int], rows: Mapping[int, tuple]) -> list[int]:
    """`sequence` with every unplaced question (`order` null) inserted after the last question of
    its section, or at the end."""
    sequence = list(sequence)
    for pk in sorted(pk for pk, (_, order) in rows.items() if order is None):
        section_id = rows[pk][0]
        at = len(sequence)
        if section_id is not None:
            for i in range(len(sequence) - 1, -1, -1):
                if rows[sequence[i]][0] == section_id:
                    at = i + 1
                    break
        sequence.insert(at, pk)
    return sequence


def split_sections(sequence: list[int], section_of: Mapping[int, int | None]) -> list[int]:
    """The sections whose questions are not one contiguous run in `sequence` (`forms:AD-4`)."""
    seen: set[int] = set()
    split: list[int] = []
    previous = None
    for pk in sequence:
        sid = section_of[pk]
        if sid is not None and sid != previous:
            if sid in seen and sid not in split:
                split.append(sid)
            seen.add(sid)
        previous = sid
    return split


def assert_forward_only(owner, positions: Mapping[int, int], field: str) -> None:
    """`forms:AD-5`: every edge on `owner` (a survey, or a learner snapshot) must target a question
    whose position is greater than its source's, under `positions` — the orders as they will be
    after the write. A violation is refused as a `ValidationError` on `field`."""
    backward = [(source, target) for source, target in _edges(owner) if positions[target] <= positions[source]]
    if backward:
        raise ValidationError(
            {field: [f"Question {target} must come after question {source}, which routes to it." for source, target in backward]}
        )


def _edges(owner) -> Iterable[tuple[int, int]]:
    """(source question id, target question id) for every go_to edge on `owner` (`forms:AD-3`)."""
    from surveys.models import AnswerSchemaOption, FlowAction, Survey
    from user_surveys.models import UserAnswerOption

    if isinstance(owner, Survey):
        options = AnswerSchemaOption.objects.filter(survey=owner)
    else:
        options = UserAnswerOption.objects.filter(user_survey=owner, question__isnull=False)
    return options.filter(flow_action=FlowAction.GO_TO, flow_target__isnull=False).values_list("question_id", "flow_target_id")
