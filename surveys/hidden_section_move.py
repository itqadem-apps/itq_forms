"""Move the hidden sections' questions to sectionless (story survey-flow 1.5, `forms:AD-9`,
`forms:AD-14`).

The second of `forms:AD-14`'s two ordered learner-data migrations, after story 1.6's survey-wide
backfill. Every question under a live hidden section moves to `section=null`, and so do its
`AnswerSchema.section` and its options' `AnswerSchemaOption.section`. No `Section` row is
deleted: the emptied hidden sections stay, and `renumber_questions` ranks them after the sections
that still hold questions.

A moved question keeps its survey-wide position. Every survey is planned before it is written,
and refused unless its rendered order is the same before and after, both under
`flat_order` and under `(order, id)`. A soft-deleted hidden section is left as it is: moving its
questions out would bring them back into the author's preview. Learner snapshots are never read
for writing (`forms:AD-2`).

Each survey is written in its own transaction, under the row lock the reorder mutations take,
so a partial run is safe to repeat: a survey already moved has no hidden section left holding a
question.

The dry run reaches production as a report-only migration (release R3a) whose output lands in the
deploy log; the move ships in the next release (R3b). There is no cluster step.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db import transaction

from surveys.question_order import flat_order, flat_question_ids, renumber_questions


class MoveRefused(Exception):
    pass


@dataclass
class HiddenSection:
    section_id: int
    title: str | None
    question_ids: list[int]  # in rendered order


@dataclass
class Plan:
    survey_id: int
    hidden: list[HiddenSection]
    fully_hidden: bool  # every live section of the survey is hidden
    before: list[int]
    render_kept: bool
    refused_reason: str = field(default="")

    @property
    def moving(self) -> list[int]:
        return [pk for sec in self.hidden for pk in sec.question_ids]


def plan_survey(survey_id: int) -> Plan:
    from surveys.models import Question, Section

    rows = {
        pk: (section_id, section_order, order)
        for pk, section_id, section_order, order in Question.objects.filter(survey_id=survey_id)
        .order_by()
        .values_list("id", "section_id", "section__order", "order")
    }
    before = flat_order([(pk, *r) for pk, r in rows.items()])
    sections = list(
        Section.objects.filter(survey_id=survey_id, deleted_at__isnull=True)
        .order_by("order", "id")
        .values_list("id", "title", "order", "is_hidden")
    )
    hidden_ids = {sid for sid, _, _, hidden in sections if hidden}
    hidden = [
        HiddenSection(sid, title, [pk for pk in before if rows[pk][0] == sid])
        for sid, title, _, is_hidden in sections
        if is_hidden
    ]

    # What `renumber_questions(sequence=before)` writes once the moved questions are sectionless:
    # orders 1..N in the rendered order, sections ranked by their first remaining question.
    section_of = {pk: (None if rows[pk][0] in hidden_ids else rows[pk][0]) for pk in before}
    current = {sid: order for sid, _, order, _ in sections}
    first: dict[int, int] = {}
    for i, pk in enumerate(before):
        if section_of[pk] is not None:
            first.setdefault(section_of[pk], i)
    held = sorted((sid for sid in first if sid in current), key=first.get)
    empty = sorted((sid for sid in current if sid not in first), key=lambda sid: (current[sid] is None, current[sid] or 0, sid))
    rank = {sid: r for r, sid in enumerate(held + empty, start=1)}
    after = [
        (pk, section_of[pk], rank.get(section_of[pk], rows[pk][1]) if section_of[pk] is not None else None, i)
        for i, pk in enumerate(before, start=1)
    ]
    by_order = [r[0] for r in sorted(after, key=lambda r: (r[3], r[0]))]

    return Plan(
        survey_id=survey_id,
        hidden=hidden,
        fully_hidden=bool(sections) and len(hidden_ids) == len(sections),
        before=before,
        render_kept=before == by_order == flat_order(after),
    )


def apply_survey(survey_id: int) -> Plan:
    from surveys.models import AnswerSchema, AnswerSchemaOption, Question, Survey

    with transaction.atomic():
        Survey.objects.select_for_update().get(pk=survey_id)
        plan = plan_survey(survey_id)
        if not plan.render_kept:
            raise MoveRefused(f"survey {survey_id}: moving its hidden sections' questions would change its rendered order")
        moving = plan.moving
        if not moving:
            return plan
        Question.objects.filter(pk__in=moving).update(section=None)
        AnswerSchema.objects.filter(question_id__in=moving).update(section=None)
        AnswerSchemaOption.objects.filter(question_id__in=moving).update(section=None)
        renumber_questions(survey_id, sequence=plan.before)
        if flat_question_ids(Question.objects.filter(survey_id=survey_id)) != plan.before:
            raise MoveRefused(f"survey {survey_id}: the rendered order changed after the move; rolled back")
        return plan


def survey_ids() -> list[int]:
    from surveys.models import Section

    return sorted(
        set(Section.objects.filter(is_hidden=True, deleted_at__isnull=True).values_list("survey_id", flat=True))
    )


def run(apply: bool, report=None) -> dict:
    """Plan (and with `apply`, write) every survey holding a live hidden section. `report(plan)` is
    called for each plan. Returns the counts, with `refused` listing why each refused survey was
    not written; every other survey was (with `apply`)."""
    counts = {"surveys": 0, "hidden_sections": 0, "questions_moved": 0, "fully_hidden_surveys": 0, "surveys_refused": 0}
    refused: list[str] = []
    for sid in survey_ids():
        try:
            plan = apply_survey(sid) if apply else plan_survey(sid)
        except MoveRefused as exc:
            plan = plan_survey(sid)
            plan.refused_reason = str(exc)
        if not plan.render_kept:
            plan.refused_reason = plan.refused_reason or f"survey {sid}: moving would change its rendered order"
        counts["surveys"] += 1
        counts["hidden_sections"] += len(plan.hidden)
        counts["fully_hidden_surveys"] += plan.fully_hidden
        if plan.refused_reason:
            counts["surveys_refused"] += 1
            refused.append(plan.refused_reason)
        else:
            counts["questions_moved"] += len(plan.moving)
        if report is not None:
            report(plan)
    counts["refused"] = refused
    return counts


def describe(plan: Plan) -> list[str]:
    """The plan as log lines, one for the survey and one per hidden section."""
    head = f"survey {plan.survey_id}" + (" (fully hidden)" if plan.fully_hidden else "")
    if plan.refused_reason:
        head += f" — REFUSED: {plan.refused_reason}"
    lines = [head]
    for sec in plan.hidden:
        lines.append(f"    section {sec.section_id} {sec.title!r}: {len(sec.question_ids)} question(s) {sec.question_ids}")
    return lines
