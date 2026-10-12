"""The builder card an add names (`forms:AD-24`): the survey card, a section heading or a question.

The anchor fixes the target survey. It is resolved through `all_objects` so a stale anchor is
still found and locked (`forms:AD-25`), then refused on `after` once the lock is held.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError

from app.graphql_ids import as_pk
from surveys.inputs import CardAnchorInput
from surveys.models import Question, Section, Survey
from surveys.question_order import flat_order


def anchor_of(after: CardAnchorInput) -> tuple[str, int]:
    named = [
        (kind, value)
        for kind, value in (("survey", after.survey_id), ("section", after.section_id), ("question", after.question_id))
        if value is not None
    ]
    if len(named) != 1:
        raise ValidationError({"after": "Name exactly one card: the survey, a section or a question."})
    kind, value = named[0]
    try:
        return kind, as_pk(value)
    except ValidationError:
        raise ValidationError({"after": f"Invalid card id: {value!r}"}) from None


def anchor_survey_id(anchor: tuple[str, int]) -> int:
    kind, pk = anchor
    try:
        if kind == "survey":
            return Survey.objects.values_list("pk", flat=True).get(pk=pk)
        if kind == "section":
            return Section.all_objects.values_list("survey_id", flat=True).get(pk=pk)
        survey_id, section_survey_id = Question.all_objects.values_list("survey_id", "section__survey_id").get(pk=pk)
        return survey_id or section_survey_id
    except (Survey.DoesNotExist, Section.DoesNotExist, Question.DoesNotExist):
        raise ValidationError({"after": "The card this follows no longer exists."})


def check_live(anchor: tuple[str, int], survey_id: int, sequence: list[int]) -> None:
    """Refuse an anchor that was deleted or does not sit in `survey_id`. Runs under the lock."""
    kind, pk = anchor
    if kind == "survey":
        live = pk == survey_id and Survey.objects.filter(pk=pk, deleted_at__isnull=True).exists()
    elif kind == "section":
        live = Section.objects.filter(pk=pk, survey_id=survey_id).exists()
    else:
        live = pk in sequence
    if not live:
        raise ValidationError({"after": "The card this follows was deleted or is not in this survey; reload the survey."})


def layout(survey_id: int) -> tuple[list[int], dict[int, int | None]]:
    """The survey's live questions in order, and the section each sits in — the set
    `renumber_questions` places (`forms:AD-21`)."""
    rows = list(Question.objects.filter(survey_id=survey_id).order_by().values_list("id", "section_id", "section__order", "order"))
    return flat_order(rows), {r[0]: r[1] for r in rows}
