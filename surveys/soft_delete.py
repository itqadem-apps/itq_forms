"""The one builder delete (`forms:AD-21`, `forms:AD-22`).

A section, question or answer option is never removed from the builder: its group is stamped with
one `deleted_at`, and the default managers stop returning it. A section stamps its live questions
and their options with its own timestamp; a question stamps its options. Deleted rows keep their
stale `order`; the live questions are renumbered and the live options resequenced.

A section or question is refused while a live option outside the deleted set has `go_to` into it
(`forms:AD-22`): the refusal is a `ValidationError` on `target_id` naming each referring option as
"Question N — option text", and nothing is written. An option is an edge source, never a target,
so its delete never blocks. The legacy `Section.submit_action_target` never blocks; references
to a deleted section are nulled.

The caller holds the survey lock (`forms:AD-25`, `surveys.survey_lock`) inside its transaction,
passes a row it read after taking it, and passes the survey id it locked, which is the one
renumbered (a legacy question has no `survey_id` of its own).
"""

from __future__ import annotations

from typing import Literal

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from surveys.models import AnswerSchemaOption, FlowAction, Question, Section
from surveys.models.signals import resequence_options
from surveys.question_order import renumber_questions

Kind = Literal["section", "question", "option"]


def _option_label(option: AnswerSchemaOption, primary_language: str | None) -> str:
    """Reads `option.translations` as prefetched by `jump_referrers`."""
    text = (option.text or "").strip()
    if not text:
        texts = {tr.language: (tr.text or "").strip() for tr in option.translations.all()}
        text = texts.get(primary_language) or next((t for t in texts.values() if t), "")
    return text or f"option {option.order}"


def jump_referrers(question_ids) -> list[str]:
    """`forms:AD-22`: each live option outside `question_ids` that jumps into them, as
    "Question N — option text", N being its question's survey-wide position ("?" while the
    question has none). An option of a deleted question, or of one under a deleted section, is
    not live and never blocks."""
    doomed = set(question_ids)
    if not doomed:
        return []
    referrers = (
        AnswerSchemaOption.objects.filter(flow_action=FlowAction.GO_TO, flow_target_id__in=doomed, question__deleted_at__isnull=True)
        .filter(Q(question__section__isnull=True) | Q(question__section__deleted_at__isnull=True))
        .exclude(question_id__in=doomed)
        .select_related("question", "survey")
        .prefetch_related("translations")
        .order_by("question__order", "order", "id")
    )
    return [
        f"Question {option.question.order if option.question.order is not None else '?'} — "
        f"{_option_label(option, option.survey.primary_language)}"
        for option in referrers
    ]


def soft_delete(kind: Kind, obj, survey_id: int) -> None:
    """Soft-delete `obj` (a `Section`, `Question` or `AnswerSchemaOption`) and its group.
    `survey_id` is the survey the caller locked."""
    stamp = timezone.now()

    if kind == "option":
        AnswerSchemaOption.all_objects.filter(pk=obj.pk).update(deleted_at=stamp)
        resequence_options(obj.schema_id)
        return

    if kind == "section":
        question_ids = list(Question.objects.filter(section_id=obj.pk).values_list("id", flat=True))
    elif kind == "question":
        question_ids = [obj.pk]
    else:
        raise ValueError(f"Unknown soft-delete kind: {kind!r}")

    referrers = jump_referrers(question_ids)
    if referrers:
        raise ValidationError({"target_id": referrers})

    if kind == "section":
        Section.all_objects.filter(submit_action_target_id=obj.pk).update(submit_action_target=None)
        Section.all_objects.filter(pk=obj.pk).update(deleted_at=stamp)
    Question.objects.filter(pk__in=question_ids).update(deleted_at=stamp)
    AnswerSchemaOption.objects.filter(question_id__in=question_ids).update(deleted_at=stamp)
    renumber_questions(survey_id)
