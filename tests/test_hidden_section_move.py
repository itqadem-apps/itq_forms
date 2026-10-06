"""Story survey-flow 1.5 — the hidden sections' questions move to sectionless (`forms:AD-9`,
`forms:AD-14`).

Fixtures mimic the live data after story 1.6's backfill: orders survey-wide 1..N, one survey with
a hidden section between two visible ones, and one survey whose every section is hidden.
"""

import importlib
import uuid

import pytest

from surveys import hidden_section_move
from surveys.models import AnswerSchema, AnswerSchemaOption, Question, Section, Survey
from surveys.question_order import flat_question_ids, renumber_questions
from user_surveys.models import UserQuestion
from user_surveys.services import enroll_user_in_assessment

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")


def _build(survey, layout):
    """`layout` is a list of (title, is_hidden); each section holds its default question plus one
    radio question."""
    sections = []
    for title, hidden in layout:
        sec = Section.objects.create(survey=survey, title=title, is_hidden=hidden)
        for n in (1,):
            Question.objects.create(survey=survey, section=sec, title=f"{title}{n}", type=Question.QUESTION_TYPE_RADIO_MCQ)
        sections.append(sec)
    renumber_questions(survey.id)
    return sections


def _rendered(survey):
    return flat_question_ids(Question.objects.filter(survey=survey))


def _by_order(survey):
    return list(Question.objects.filter(survey=survey).order_by("order", "id").values_list("id", flat=True))


@pytest.fixture
def mixed(survey):
    return _build(survey, [("A", False), ("H", True), ("B", False)])


@pytest.fixture
def fully_hidden(db):
    s = Survey.objects.create(organization_id=ORG)
    return s, _build(s, [("X", True), ("Y", True)])


# ── Dry run ─────────────────────────────────────────────────────


def test_the_dry_run_reports_hidden_sections_and_writes_nothing(survey, mixed, fully_hidden):
    other, _ = fully_hidden
    sections = {s.pk: list(s.questions.values_list("id", flat=True)) for s in Section.objects.all()}

    plans = []
    counts = hidden_section_move.run(apply=False, report=plans.append)

    assert {s.pk: list(s.questions.values_list("id", flat=True)) for s in Section.objects.all()} == sections
    assert counts["surveys"] == 2
    assert counts["hidden_sections"] == 3
    assert counts["questions_moved"] == 6
    assert counts["fully_hidden_surveys"] == 1
    assert counts["surveys_refused"] == 0
    by_survey = {p.survey_id: p for p in plans}
    assert not by_survey[survey.id].fully_hidden and by_survey[other.id].fully_hidden
    assert [h.section_id for h in by_survey[survey.id].hidden] == [mixed[1].pk]
    assert "section" in "\n".join(hidden_section_move.describe(by_survey[survey.id]))


def test_a_soft_deleted_hidden_section_is_left_alone(survey, mixed):
    Section.objects.filter(pk=mixed[1].pk).update(deleted_at="2026-01-01T00:00:00Z")
    assert hidden_section_move.run(apply=True)["surveys"] == 0
    assert mixed[1].questions.count() == 2


# ── Apply ───────────────────────────────────────────────────────


def test_apply_moves_the_questions_and_their_schemas_and_options_to_sectionless(survey, mixed):
    hidden = mixed[1]
    moved = list(hidden.questions.values_list("id", flat=True))

    hidden_section_move.run(apply=True)

    assert set(Question.objects.filter(section__isnull=True).values_list("id", flat=True)) == set(moved)
    assert not AnswerSchema.objects.filter(question_id__in=moved, section__isnull=False).exists()
    assert AnswerSchemaOption.objects.filter(question_id__in=moved).exists()
    assert not AnswerSchemaOption.objects.filter(question_id__in=moved, section__isnull=False).exists()
    assert AnswerSchemaOption.objects.filter(question__section=mixed[0], section=mixed[0]).exists()


def test_no_section_row_is_deleted_and_the_emptied_one_ranks_last(survey, mixed):
    hidden_section_move.run(apply=True)

    a, h, b = (Section.objects.get(pk=s.pk) for s in mixed)
    assert (a.order, b.order, h.order) == (1, 2, 3)


def test_every_moved_question_keeps_its_position_and_the_render_is_unchanged(survey, mixed, fully_hidden):
    other, _ = fully_hidden
    before = {s: _rendered(s) for s in (survey, other)}
    orders = dict(Question.objects.values_list("id", "order"))

    hidden_section_move.run(apply=True)

    for s in (survey, other):
        assert _rendered(s) == before[s] == _by_order(s)
    assert dict(Question.objects.values_list("id", "order")) == orders


def test_open_learner_snapshots_are_not_touched(survey, mixed, user):
    us, _ = enroll_user_in_assessment(user, survey.id)
    snapshot = list(UserQuestion.objects.filter(user_survey=us).values_list("id", "section_id", "order"))

    hidden_section_move.run(apply=True)

    assert list(UserQuestion.objects.filter(user_survey=us).values_list("id", "section_id", "order")) == snapshot


def test_a_second_run_finds_nothing_to_move(survey, mixed):
    hidden_section_move.run(apply=True)
    counts = hidden_section_move.run(apply=True)
    assert counts["questions_moved"] == 0 and counts["surveys_refused"] == 0


def test_a_survey_whose_render_would_change_is_refused_not_written(survey, mixed, fully_hidden, monkeypatch):
    planner = hidden_section_move.plan_survey

    def plan(sid):
        p = planner(sid)
        p.render_kept = p.render_kept and sid != survey.id
        return p

    monkeypatch.setattr(hidden_section_move, "plan_survey", plan)
    hidden = list(mixed[1].questions.values_list("id", flat=True))

    counts = hidden_section_move.run(apply=True)

    assert counts["surveys_refused"] == 1 and counts["questions_moved"] == 4
    assert list(Question.objects.filter(pk__in=hidden).values_list("section_id", flat=True)) == [mixed[1].pk] * 2
    assert not Question.objects.filter(survey=fully_hidden[0], section__isnull=False).exists()


# ── Release R3a: the report-only migration ──────────────────────


def test_the_report_migration_prints_the_plan_and_writes_nothing(survey, mixed, capsys):
    migration = importlib.import_module("surveys.migrations.0048_report_hidden_section_move")
    sections = dict(Question.objects.values_list("id", "section_id"))

    migration.forwards(None, None)

    out = capsys.readouterr().out
    assert dict(Question.objects.values_list("id", "section_id")) == sections
    assert f"section {mixed[1].pk} 'H': 2 question(s)" in out
    assert "summary: 1 surveys, 1 hidden sections, 2 questions to move, 0 fully hidden, 0 refused" in out
    assert migration.Migration.operations[0].reversible


# ── Release R3b: the move migration ─────────────────────────────


def _move_migration():
    return importlib.import_module("surveys.migrations.0049_move_hidden_sections_to_sectionless")


def test_the_move_migration_runs_the_same_move(survey, mixed):
    before = _rendered(survey)
    _move_migration().forwards(None, None)
    assert not Question.objects.filter(section=mixed[1]).exists()
    assert _rendered(survey) == before == _by_order(survey)


def test_the_move_migration_fails_the_release_on_a_refused_survey(survey, mixed, monkeypatch):
    planner = hidden_section_move.plan_survey

    def plan(sid):
        p = planner(sid)
        p.render_kept = False
        return p

    monkeypatch.setattr(hidden_section_move, "plan_survey", plan)
    with pytest.raises(RuntimeError, match="refused"):
        _move_migration().forwards(None, None)


def test_the_move_migration_is_reversible_and_not_atomic():
    migration = _move_migration().Migration
    assert migration.operations[0].reversible
    assert migration.atomic is False
