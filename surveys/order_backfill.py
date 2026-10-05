"""The survey-wide order backfill (story survey-flow 1.6, `forms:AD-4`, `forms:AD-14`).

Two kinds of owner are renumbered 1..N:

* **every survey** — reached only through `renumber_questions(survey_id, sequence=...)`, with the
  sequence taken by the legacy key `(section.order nulls last, question.order, id)`, i.e.
  `flat_question_ids`. `Section.order` is re-derived by the same call;
* **every open (unsubmitted) learner snapshot** — by `(UserSection.order nulls last,
  UserQuestion.order, id)`, again `flat_question_ids`. A shuffled attempt keeps its in-section
  order and its sections become contiguous. `UserSection.order` is not touched. Submitted
  snapshots are never read for writing.

Both keys are `flat_question_ids` rather than the bare legacy sort because that is what renders
today: it *is* the legacy key, except on a set whose orders are already survey-wide and which
holds a sectionless question between sections (`forms:AD-18`) — there the bare legacy key would
move that question last, which is a change to what the learner sees.

Every owner is planned before anything is written, and the plan is refused unless the rendered
order is the same before and after — both under `flat_question_ids` and under `(order, id)`,
which is what `Question.Meta.ordering = ["order"]` reads once it flips. `assert_forward_only`
(`forms:AD-5`) runs against the new positions; it passes, since no survey carries an edge.

Each owner is written in its own transaction, under a row lock on the survey (the lock the
reorder mutations take) or the attempt, so a partial run is safe to repeat: an owner already
1..N plans no change.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db import transaction

from surveys.question_order import _appended, assert_forward_only, flat_order, renumber_questions


class BackfillRefused(Exception):
    pass


@dataclass
class Plan:
    kind: str  # "survey" | "snapshot"
    owner_id: int
    rows: dict[int, tuple]  # id -> (section_id, section_order, order), as found
    before: list[int]  # the rendered order now
    sequence: list[int]  # the order 1..N will follow
    render_kept: bool
    sections_reranked: int = 0
    refused_reason: str = field(default="")

    @property
    def changes(self) -> list[tuple[int, int | None, int]]:
        return [(pk, self.rows[pk][2], i) for i, pk in enumerate(self.sequence, start=1) if self.rows[pk][2] != i]

    @property
    def affected(self) -> bool:
        return bool(self.changes or self.sections_reranked)


def _rows(queryset) -> dict[int, tuple]:
    return {
        pk: (section_id, section_order, order)
        for pk, section_id, section_order, order in queryset.order_by().values_list(
            "id", "section_id", "section__order", "order"
        )
    }


def _as_flat(rows: dict[int, tuple]) -> list[tuple]:
    return [(pk, sid, sorder, order) for pk, (sid, sorder, order) in rows.items()]


def _render_kept(before: list[int], sequence: list[int], rows_after: dict[int, tuple]) -> bool:
    by_order = sorted(rows_after, key=lambda pk: (rows_after[pk][2], pk))
    return before == sequence == by_order == flat_order(_as_flat(rows_after))


def plan_survey(survey_id: int) -> Plan:
    from surveys.models import Question, Section

    rows = _rows(Question.objects.filter(survey_id=survey_id))
    before = flat_order(_as_flat(rows))
    placed = {pk: r for pk, r in rows.items() if r[2] is not None}
    # Exactly `renumber_questions`' own default before story 1.6: the legacy key, with any
    # unplaced question appended to its section.
    sequence = _appended(flat_order(_as_flat(placed)), {pk: (r[0], r[2]) for pk, r in rows.items()})

    first: dict[int, int] = {}
    for i, pk in enumerate(sequence):
        if rows[pk][0] is not None:
            first.setdefault(rows[pk][0], i)
    # The ranking `renumber_questions` writes: the survey's own sections by their first question,
    # empty ones after. A section of another survey that a question points at keeps its order.
    current = dict(Section.objects.filter(survey_id=survey_id).order_by().values_list("id", "order"))
    held = sorted((sid for sid in first if sid in current), key=first.get)
    empty = sorted((sid for sid in current if sid not in first), key=lambda sid: (current[sid] is None, current[sid] or 0, sid))
    section_after = {sid: rank for rank, sid in enumerate(held + empty, start=1)}
    reranked = sum(1 for sid, rank in section_after.items() if current[sid] != rank)
    rows_after = {
        pk: (rows[pk][0], section_after.get(rows[pk][0], rows[pk][1]), i) for i, pk in enumerate(sequence, start=1)
    }

    return Plan(
        kind="survey",
        owner_id=survey_id,
        rows=rows,
        before=before,
        sequence=sequence,
        render_kept=_render_kept(before, sequence, rows_after),
        sections_reranked=reranked,
    )


def plan_snapshot(user_survey_id: int) -> Plan:
    from user_surveys.models import UserQuestion

    rows = _rows(UserQuestion.objects.filter(user_survey_id=user_survey_id))
    before = flat_order(_as_flat(rows))
    sequence = list(before)
    rows_after = {pk: (rows[pk][0], rows[pk][1], i) for i, pk in enumerate(sequence, start=1)}
    return Plan(
        kind="snapshot",
        owner_id=user_survey_id,
        rows=rows,
        before=before,
        sequence=sequence,
        render_kept=_render_kept(before, sequence, rows_after),
    )


def apply_survey(survey_id: int, allow_render_change: bool = False) -> Plan:
    from surveys.models import Survey

    with transaction.atomic():
        survey = Survey.objects.select_for_update().get(pk=survey_id)
        plan = plan_survey(survey_id)
        if not plan.render_kept and not allow_render_change:
            raise BackfillRefused(f"survey {survey_id}: renumbering would change its rendered order")
        if not plan.affected:
            return plan
        positions = {pk: i for i, pk in enumerate(plan.sequence, start=1)}
        assert_forward_only(survey, positions, field="order")
        written = renumber_questions(survey_id, sequence=plan.sequence)
        if written != plan.sequence:
            raise BackfillRefused(f"survey {survey_id}: renumber_questions wrote a different sequence than planned")
        return plan


def apply_snapshot(user_survey_id: int) -> Plan | None:
    from user_surveys.models import UserQuestion, UserSurvey

    with transaction.atomic():
        user_survey = UserSurvey.objects.select_for_update().get(pk=user_survey_id)
        if user_survey.submitted_at is not None:
            return None  # submitted since it was listed; submitted snapshots are never touched
        plan = plan_snapshot(user_survey_id)
        if not plan.render_kept:
            raise BackfillRefused(f"snapshot {user_survey_id}: renumbering would change its rendered order")
        changes = plan.changes
        if not changes:
            return plan
        assert_forward_only(user_survey, {pk: i for i, pk in enumerate(plan.sequence, start=1)}, field="order")
        UserQuestion.objects.bulk_update([UserQuestion(pk=pk, order=new) for pk, _, new in changes], ["order"])
        return plan


def survey_ids(only: list[int] | None = None) -> list[int]:
    from surveys.models import Question

    qs = Question.objects.filter(survey_id__isnull=False)
    if only:
        qs = qs.filter(survey_id__in=only)
    return sorted(set(qs.values_list("survey_id", flat=True)))


def open_snapshot_ids(only_surveys: list[int] | None = None) -> list[int]:
    from user_surveys.models import UserQuestion

    qs = UserQuestion.objects.filter(user_survey__submitted_at__isnull=True)
    if only_surveys:
        qs = qs.filter(user_survey__survey_id__in=only_surveys)
    return sorted(set(qs.values_list("user_survey_id", flat=True)))


def run(apply: bool, only_surveys: list[int] | None = None, allow_render_change: bool = False, report=None) -> dict:
    """Plan (and with `apply`, write) every survey, then every open snapshot. `report(plan)` is
    called for each plan. Returns the counts, with `refused` listing why each refused owner was not
    written; every other owner was (with `apply`). The caller decides whether that is a failure."""
    counts = {
        "surveys": 0, "surveys_affected": 0, "surveys_refused": 0,
        "snapshots": 0, "snapshots_affected": 0, "snapshots_refused": 0,
    }
    refused: list[str] = []

    def visit(kind, owner_id, planner, applier):
        counts[kind] += 1
        try:
            plan = applier(owner_id) if apply else planner(owner_id)
        except BackfillRefused as exc:
            plan = planner(owner_id)
            plan.refused_reason = str(exc)
        if plan is None:
            return
        if not plan.render_kept and not (kind == "surveys" and allow_render_change):
            plan.refused_reason = plan.refused_reason or "renumbering would change its rendered order"
        if plan.refused_reason:
            counts[f"{kind}_refused"] += 1
            refused.append(plan.refused_reason)
        elif plan.affected:
            counts[f"{kind}_affected"] += 1
        if report is not None:
            report(plan)

    for sid in survey_ids(only_surveys):
        visit("surveys", sid, plan_survey, lambda pk: apply_survey(pk, allow_render_change))
    for usid in open_snapshot_ids(only_surveys):
        visit("snapshots", usid, plan_snapshot, apply_snapshot)

    counts["refused"] = refused
    return counts
