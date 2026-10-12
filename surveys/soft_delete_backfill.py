"""Stamp the live children of rows already soft-deleted (story surveys-builder 3.2, `forms:AD-21`,
`forms:AD-14`).

`forms:AD-21` makes each default manager filter on its own `deleted_at` only, which is correct
once no live child sits under a deleted parent. Before it, a soft-deleted section left its
questions live, and a soft-deleted question left its options live (`AnswerSchemaOption` had no
`deleted_at` until 0056). This finds those orphans and stamps each with its parent's
`deleted_at`, the same group stamp a builder delete writes from now on:

- a live question under a deleted section takes the section's `deleted_at`;
- a live option whose question is deleted takes the question's `deleted_at`, or, when the
  question is live but under a deleted section, the section's (the question is stamped with the
  same value in the same pass).

An option whose own `section` column names a deleted section while its question is live and
elsewhere is a stale section column, not an orphan: it is counted in the report and left alone.

A live option that `go_to`s a deleted question (or one under a deleted section) is a dangling
edge: before 3.2 the hard delete's `pre_delete` turned such edges into fall-throughs, but a soft
delete never fired it. Enrolment after R3 cannot place its target and raises, so the apply turns
it into a fall-through (`flow_action` fall_through, `flow_target` null), as `clear_edges_into`
did.

A question belongs to its `survey_id`, or, for a legacy row without one, to its section's
survey. A question with neither cannot be placed in any survey: it is reported and never written.

Reads go through `_base_manager`, which never filters, so the module behaves the same before and
after the managers switch. Each survey is planned again and written in its own transaction under
the survey lock (`forms:AD-25`), reading only that survey's rows, so a partial run is safe to
repeat. Learner snapshots are never read or written.

The report ships as migration 0057 (writes nothing); the apply ships as 0058 in its own release.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from django.db import transaction
from django.db.models import Q


@dataclass
class Plan:
    survey_id: int
    # (question id, the deleted section it sits under, that section's deleted_at)
    questions: list[tuple[int, int, datetime]] = field(default_factory=list)
    # (option id, its question id, the deleted_at it takes)
    options: list[tuple[int, int, datetime]] = field(default_factory=list)
    # (live option id, its question id, the deleted question it jumps to): made fall-through
    jumps: list[tuple[int, int, int]] = field(default_factory=list)
    stale_option_sections: int = 0

    def __bool__(self) -> bool:
        return bool(self.questions or self.options or self.jumps or self.stale_option_sections)


def _rows(survey_id: int | None = None):
    """Deleted sections, questions as {id: (survey key, section id, deleted_at)}, and live
    options. With `survey_id`, only that survey's rows (and the questions its options name)."""
    from surveys.models import AnswerSchemaOption, Question, Section

    sections = Section._base_manager.filter(deleted_at__isnull=False)
    questions = Question._base_manager.order_by()
    options = AnswerSchemaOption._base_manager.filter(deleted_at__isnull=True)
    if survey_id is not None:
        sections = sections.filter(survey_id=survey_id)
        options = options.filter(survey_id=survey_id)
        questions = questions.filter(
            Q(survey_id=survey_id) | Q(survey_id__isnull=True, section__survey_id=survey_id) | Q(pk__in=options.values("question_id"))
        )
    deleted_sections = dict(sections.values_list("id", "deleted_at"))
    question_rows = {
        pk: (own or via_section, section_id, deleted_at)
        for pk, own, via_section, section_id, deleted_at in questions.values_list(
            "id", "survey_id", "section__survey_id", "section_id", "deleted_at"
        )
    }
    option_rows = list(
        options.order_by("id").values_list("id", "survey_id", "question_id", "section_id", "flow_action", "flow_target_id")
    )
    return deleted_sections, question_rows, option_rows


def plan(survey_id: int | None = None) -> list[Plan]:
    """Every survey (or only `survey_id`) holding an orphan or a dangling edge, read and never
    written."""
    from surveys.models import FlowAction

    deleted_sections, questions, options = _rows(survey_id)
    plans: dict[int, Plan] = {}

    def at(key):
        return plans.setdefault(key, Plan(key))

    effective: dict[int, datetime] = {}
    for pk, (key, section_id, deleted_at) in sorted(questions.items()):
        if deleted_at is not None:
            effective[pk] = deleted_at
        elif section_id in deleted_sections:
            effective[pk] = deleted_sections[section_id]
            if key is not None:
                at(key).questions.append((pk, section_id, deleted_sections[section_id]))

    for pk, option_survey_id, question_id, section_id, flow_action, target_id in options:
        if question_id in effective:
            at(option_survey_id).options.append((pk, question_id, effective[question_id]))
        else:
            if section_id in deleted_sections:
                at(option_survey_id).stale_option_sections += 1
            if flow_action == FlowAction.GO_TO and target_id in effective:
                at(option_survey_id).jumps.append((pk, question_id, target_id))

    return [plans[k] for k in sorted(plans) if plans[k]]


def unresolved_questions() -> list[int]:
    """Live questions with neither a survey nor a section: reported, never written."""
    from surveys.models import Question

    return sorted(
        Question._base_manager.filter(survey_id__isnull=True, section__isnull=True, deleted_at__isnull=True).values_list("id", flat=True)
    )


def _stamp(model, rows) -> int:
    by_stamp: dict[datetime, list[int]] = {}
    for pk, _, stamp in rows:
        by_stamp.setdefault(stamp, []).append(pk)
    return sum(
        model._base_manager.filter(pk__in=ids, deleted_at__isnull=True).update(deleted_at=stamp)
        for stamp, ids in by_stamp.items()
    )


def apply_survey(survey_id: int) -> Plan | None:
    from surveys.models import AnswerSchemaOption, FlowAction, Question, Survey

    with transaction.atomic():
        Survey._base_manager.select_for_update().filter(pk=survey_id).values_list("pk", flat=True).first()
        current = next(iter(plan(survey_id)), None)
        if current is None:
            return None
        _stamp(Question, current.questions)
        _stamp(AnswerSchemaOption, current.options)
        if current.jumps:
            AnswerSchemaOption._base_manager.filter(
                pk__in=[pk for pk, _, _ in current.jumps], deleted_at__isnull=True, flow_action=FlowAction.GO_TO
            ).update(flow_action=FlowAction.FALL_THROUGH, flow_target=None)
        return current


def run(apply: bool, report=None) -> dict:
    """Plan (and with `apply`, write) every survey holding an orphan or a dangling edge.
    `report(plan)` is called for each plan. Returns the counts."""
    counts = {"surveys": 0, "questions": 0, "options": 0, "jumps": 0, "stale_option_sections": 0}
    for p in plan():
        if apply:
            p = apply_survey(p.survey_id) or p
        counts["surveys"] += 1
        counts["questions"] += len(p.questions)
        counts["options"] += len(p.options)
        counts["jumps"] += len(p.jumps)
        counts["stale_option_sections"] += p.stale_option_sections
        if report is not None:
            report(p)
    counts["unresolved_questions"] = unresolved_questions()
    return counts


def summary(counts: dict, applied: bool) -> list[str]:
    """The run's closing lines."""
    stamp, edge = ("stamped", "made fall-through") if applied else ("to stamp", "to make fall-through")
    lines = [
        f"summary: {counts['surveys']} surveys, {counts['questions']} questions, {counts['options']} options {stamp}, "
        f"{counts['jumps']} dangling go_to edges {edge}, "
        f"{counts['stale_option_sections']} stale option section columns left alone"
    ]
    if counts["unresolved_questions"]:
        lines.append(f"live question(s) with no survey and no section, left alone: {counts['unresolved_questions']}")
    return lines


def describe(p: Plan) -> list[str]:
    """The plan as log lines: one for the survey, one per deleted parent."""
    lines = [
        f"survey {p.survey_id}: {len(p.questions)} question(s), {len(p.options)} option(s) to stamp, "
        f"{len(p.jumps)} dangling go_to edge(s) to fall through"
        + (f", {p.stale_option_sections} option(s) with a stale deleted section column left alone" if p.stale_option_sections else "")
    ]
    by_section: dict[int, list[int]] = {}
    for pk, section_id, _ in p.questions:
        by_section.setdefault(section_id, []).append(pk)
    for section_id, ids in by_section.items():
        lines.append(f"    deleted section {section_id}: live question(s) {ids}")
    by_question: dict[int, list[int]] = {}
    for pk, question_id, _ in p.options:
        by_question.setdefault(question_id, []).append(pk)
    for question_id, ids in by_question.items():
        lines.append(f"    question {question_id} (deleted, or under a deleted section): live option(s) {ids}")
    for pk, question_id, target_id in p.jumps:
        lines.append(f"    option {pk} of live question {question_id}: go_to deleted question {target_id} -> fall_through")
    return lines
