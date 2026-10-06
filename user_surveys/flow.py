"""The current path through a learner's snapshot, and what an answer advances to (`forms:AD-6`,
`forms:AD-8`, `forms:AD-17`, `forms:AD-19`).

`walk` is the one function that computes the path. The answer write and every terminal transition
call it through `recalculate_on_path`; the advance result is read off its output. It is pure over
plain rows so the on_path report migration can run it on historical models.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from surveys.question_order import flat_order

GO_TO = "go_to"
TERMINATE = "terminate"

# The closed end-reason enum (`forms:AD-6`).
ROUTING_TERMINATE = "routing_terminate"
ENDING_THRESHOLD = "ending_threshold"
FALLTHROUGH_COMPLETE = "fallthrough_complete"
FORCE_TERMINATED = "force_terminated"

# `UserSurvey.termination_reason` keeps its stored values; the API reads them through this map.
STORED_TO_END_REASON = {
    "completed": FALLTHROUGH_COMPLETE,
    "time_expired": FORCE_TERMINATED,
    "ending_option": ENDING_THRESHOLD,
    "routing_terminate": ROUTING_TERMINATE,
}


@dataclass(frozen=True)
class Walk:
    path: list[int]
    # How the path ends: ROUTING_TERMINATE at an answered terminate, else FALLTHROUGH_COMPLETE.
    end: str


def walk(sequence: list[int], routing: Mapping[int, tuple[str, int | None]]) -> Walk:
    """From the first question in snapshot order: an answered go_to continues at its target, an
    answered terminate ends the path there, and everything else — a fall_through option, a blank
    question, a question with no options, a calculation — falls through. No loop guard:
    `forms:AD-5` keeps every edge forward."""
    position = {pk: i for i, pk in enumerate(sequence)}
    path: list[int] = []
    i = 0
    while i < len(sequence):
        pk = sequence[i]
        path.append(pk)
        action, target = routing.get(pk, (None, None))
        if action == TERMINATE:
            return Walk(path, ROUTING_TERMINATE)
        i = position[target] if action == GO_TO and target in position else i + 1
    return Walk(path, FALLTHROUGH_COMPLETE)


def routing_of(answered: Iterable[tuple[int, str | None, int | None]]) -> dict[int, tuple[str, int | None]]:
    """(question id, selected option's flow_action, flow_target_id) rows → the one edge each
    answered question follows. Only a single-select option can route (`forms:AD-3`), so a question
    yields at most one go_to or terminate."""
    routing: dict[int, tuple[str, int | None]] = {}
    for question_id, action, target in answered:
        if action in (GO_TO, TERMINATE):
            routing[question_id] = (action, target)
    return routing


def walk_snapshot(user_survey, question_model, answer_model) -> Walk:
    """`walk` over one attempt's stored snapshot and answers. Takes the model classes so a
    migration can pass its historical ones."""
    rows = list(
        question_model.objects.filter(user_survey=user_survey)
        .order_by()
        .values_list("id", "section_id", "section__order", "order")
    )
    answered = answer_model.objects.filter(user_survey=user_survey).values_list(
        "question_id", "selected_options__flow_action", "selected_options__flow_target_id"
    )
    return walk(flat_order(rows), routing_of(answered))


def current_walk(user_survey) -> Walk:
    from user_surveys.models import UserAnswer, UserQuestion

    return walk_snapshot(user_survey, UserQuestion, UserAnswer)


def recalculate_on_path(user_survey) -> Walk:
    """`forms:AD-17`: store the walk on the learner's rows. Questions upstream of a write cannot
    change, so rewriting only the flags that differ touches exactly the downstream ones."""
    from user_surveys.models import UserQuestion

    result = current_walk(user_survey)
    snapshot = UserQuestion.objects.filter(user_survey=user_survey)
    snapshot.filter(pk__in=result.path, on_path=False).update(on_path=True)
    snapshot.exclude(pk__in=result.path).filter(on_path=True).update(on_path=False)
    return result


@dataclass(frozen=True)
class Advance:
    """Exactly one of the two is set (`forms:AD-6`)."""

    next_question_id: int | None = None
    end: str | None = None


def advance_from(result: Walk, sequence_position: Mapping[int, int], question_id: int) -> Advance:
    """The next on-path question after `question_id`, answered or not, or how the path ends there.
    A question off the path advances to the first on-path question after it."""
    at = sequence_position[question_id]
    for pk in result.path:
        if sequence_position[pk] > at:
            return Advance(next_question_id=pk)
    return Advance(end=result.end)
