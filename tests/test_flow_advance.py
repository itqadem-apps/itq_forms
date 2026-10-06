"""Story survey-flow 2.3 — the server decides the next question and says so in one shape
(`forms:AD-6`, `forms:AD-7`, `forms:AD-8`, `forms:AD-17`, `forms:AD-19`)."""

import importlib

import pytest
from django.apps import apps

from surveys.models import AnswerSchemaOption, FlowAction, Question, Survey
from surveys.question_order import renumber_questions
from user_surveys import flow
from user_surveys.models import UserAnswer, UserAnswerOption, UserQuestion, UserSurvey
from user_surveys.schemas.mutations.answer_question import AnswerQuestionMutation
from user_surveys.schemas.queries.should_terminate import ShouldTerminateQuery
from user_surveys.services import enroll_user_in_assessment, finish_assessment
from user_surveys.types import EndReason, UserAnswerType
from user_surveys.types.user_survey import AttemptEnded, NextQuestion


def _resolver(cls, name):
    field = next(f for f in cls.__strawberry_definition__.fields if f.python_name == name)
    fn = field.base_resolver.wrapped_func
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def _question(survey, title, q_type=Question.QUESTION_TYPE_RADIO_MCQ, is_required=False):
    return Question.objects.create(survey=survey, section=None, title=title, type=q_type, is_required=is_required)


def _second_option(question):
    return AnswerSchemaOption.objects.create(
        schema=question.answer_schema, survey_id=question.survey_id, question_id=question.id
    )


def _route(option, action, target=None, **extra):
    AnswerSchemaOption.objects.filter(pk=option.pk).update(flow_action=action, flow_target=target, **extra)
    return option


@pytest.fixture
def qs(survey):
    """q1..q5, sectionless, in that order; each has one option and q1 a second."""
    questions = [_question(survey, f"q{i}") for i in range(1, 6)]
    renumber_questions(survey.id, [q.id for q in questions])
    return questions


def _first(question):
    return question.answer_schema.options.order_by("id").first()


def _enrol(user, survey):
    us, _ = enroll_user_in_assessment(user, survey.id)
    return us


def _mine(us, question):
    return UserQuestion.objects.get(user_survey=us, origin_id=question.id)


def _answer(us, question, option=None, text=None):
    uq = _mine(us, question)
    if option is not None:
        values = [str(UserAnswerOption.objects.get(user_survey=us, origin_id=option.id).id)]
    else:
        values = [text or ""]
    return _resolver(AnswerQuestionMutation, "answer_question")(
        AnswerQuestionMutation(), None, user_survey_id=str(us.id), question_id=str(uq.id),
        answer=values, django_user=us.user,
    )


def _advance(user_answer):
    return _resolver(UserAnswerType, "advance")(user_answer)


def _should_terminate(us):
    return _resolver(ShouldTerminateQuery, "should_terminate")(
        ShouldTerminateQuery(), None, user_survey_id=str(us.id), django_user=us.user
    )


def _on_path(us):
    return {q.origin_id for q in UserQuestion.objects.filter(user_survey=us, on_path=True)}


# ── The walk ────────────────────────────────────────────────────


def test_walk_follows_go_to_ends_at_terminate_and_falls_through_otherwise():
    seq = [1, 2, 3, 4, 5]
    assert flow.walk(seq, {}) == flow.Walk([1, 2, 3, 4, 5], flow.FALLTHROUGH_COMPLETE)
    assert flow.walk(seq, {1: ("go_to", 4)}) == flow.Walk([1, 4, 5], flow.FALLTHROUGH_COMPLETE)
    assert flow.walk(seq, {1: ("go_to", 3), 3: ("terminate", None)}) == flow.Walk([1, 3], flow.ROUTING_TERMINATE)
    # An answered question off the path does not route.
    assert flow.walk(seq, {1: ("go_to", 4), 2: ("terminate", None)}).path == [1, 4, 5]


def test_routing_ignores_fall_through_and_unanswered_options():
    assert flow.routing_of([(1, "fall_through", None), (2, None, None), (3, "go_to", 5)]) == {3: ("go_to", 5)}


# ── Advancing ───────────────────────────────────────────────────


def test_go_to_advances_to_its_target_and_takes_the_skipped_questions_off_path(survey, qs, user):
    q1, q2, q3, q4, q5 = qs
    _route(_first(q1), FlowAction.GO_TO, q4)
    us = _enrol(user, survey)

    result = _advance(_answer(us, q1, _first(q1)))

    assert isinstance(result, NextQuestion)
    assert result.question_id == _mine(us, q4).id and result.question.id == result.question_id
    assert _on_path(us) == {q1.id, q4.id, q5.id}


def test_fall_through_advances_in_snapshot_order(survey, qs, user):
    us = _enrol(user, survey)
    result = _advance(_answer(us, qs[0], _first(qs[0])))
    assert isinstance(result, NextQuestion) and result.question_id == _mine(us, qs[1]).id


def test_falling_through_the_last_question_completes_without_auto_submitting(survey, qs, user):
    us = _enrol(user, survey)
    result = _advance(_answer(us, qs[-1], _first(qs[-1])))

    assert isinstance(result, AttemptEnded) and result.reason == EndReason.FALLTHROUGH_COMPLETE
    # As today: reaching the end hands the submit to the solver.
    assert UserSurvey.objects.get(pk=us.pk).submitted_at is None


def test_a_routing_terminate_ends_the_attempt_on_the_write(survey, qs, user):
    _route(_first(qs[1]), FlowAction.TERMINATE)
    us = _enrol(user, survey)

    result = _advance(_answer(us, qs[1], _first(qs[1])))

    us.refresh_from_db()
    assert us.submitted_at is not None and us.termination_reason == UserSurvey.TERMINATION_ROUTING
    assert isinstance(result, AttemptEnded) and result.reason == EndReason.ROUTING_TERMINATE
    assert _should_terminate(us) == EndReason.ROUTING_TERMINATE
    assert _on_path(us) == {qs[0].id, qs[1].id}


@pytest.mark.parametrize("threshold_met", [False, True])
def test_terminate_wins_over_an_ending_option_on_the_same_option(survey, qs, user, threshold_met):
    _route(_first(qs[0]), FlowAction.TERMINATE, ending_option=True)
    Survey.objects.filter(pk=survey.pk).update(
        allow_end_based_on_answer_repeat=True, answers_count_to_end=1 if threshold_met else 3
    )
    us = _enrol(user, survey)

    result = _advance(_answer(us, qs[0], _first(qs[0])))

    assert UserSurvey.objects.get(pk=us.pk).termination_reason == UserSurvey.TERMINATION_ROUTING
    assert result.reason == EndReason.ROUTING_TERMINATE


def test_the_ending_threshold_alone_behaves_as_before(survey, qs, user):
    AnswerSchemaOption.objects.filter(pk=_first(qs[0]).pk).update(ending_option=True)
    Survey.objects.filter(pk=survey.pk).update(allow_end_based_on_answer_repeat=True, answers_count_to_end=1)
    us = _enrol(user, survey)

    result = _advance(_answer(us, qs[0], _first(qs[0])))

    assert result.reason == EndReason.ENDING_THRESHOLD
    # Still finished by the poll, exactly as today.
    assert UserSurvey.objects.get(pk=us.pk).submitted_at is None
    assert _should_terminate(us) == EndReason.ENDING_THRESHOLD
    assert UserSurvey.objects.get(pk=us.pk).termination_reason == UserSurvey.TERMINATION_ENDING_OPTION


# ── Going back ──────────────────────────────────────────────────


def test_going_back_and_changing_branch_recalculates_the_path_and_keeps_answers(survey, qs, user):
    q1, q2, q3, q4, q5 = qs
    skip = _route(_first(q1), FlowAction.GO_TO, q4)
    stay = _second_option(q1)
    us = _enrol(user, survey)
    _answer(us, q1, skip)
    _answer(us, q4, _first(q4))
    assert _on_path(us) == {q1.id, q4.id, q5.id}

    result = _advance(_answer(us, q1, stay))

    assert result.question_id == _mine(us, q2).id
    assert _on_path(us) == {q.id for q in qs}
    assert UserAnswer.objects.filter(user_survey=us, question=_mine(us, q4)).exists()


def test_advance_returns_the_next_on_path_question_even_if_already_answered(survey, qs, user):
    q1, q2, q3, q4, q5 = qs
    skip = _route(_first(q1), FlowAction.GO_TO, q4)
    us = _enrol(user, survey)
    _answer(us, q1, skip)
    _answer(us, q4, _first(q4))

    assert _advance(_answer(us, q1, skip)).question_id == _mine(us, q4).id


# ── Blank questions and completion ──────────────────────────────


def test_a_blank_question_never_stops_the_walk(survey, qs, user):
    text = _question(survey, "free", q_type=Question.QUESTION_TYPE_TEXT, is_required=True)
    renumber_questions(survey.id, [qs[0].id, text.id, *(q.id for q in qs[1:])])
    _route(_first(qs[2]), FlowAction.GO_TO, qs[4])
    us = _enrol(user, survey)

    _answer(us, qs[2], _first(qs[2]))

    assert _on_path(us) == {qs[0].id, text.id, qs[1].id, qs[2].id, qs[4].id}


def test_a_required_question_the_path_skipped_does_not_block_submit(survey, qs, user):
    Question.objects.filter(pk=qs[1].pk).update(is_required=True)
    _route(_first(qs[0]), FlowAction.GO_TO, qs[2])
    us = _enrol(user, survey)
    _answer(us, qs[0], _first(qs[0]))

    finish_assessment(us)
    assert UserSurvey.objects.get(pk=us.pk).submitted_at is not None


def test_a_required_on_path_question_still_blocks_submit(survey, qs, user):
    Question.objects.filter(pk=qs[1].pk).update(is_required=True)
    us = _enrol(user, survey)
    _answer(us, qs[0], _first(qs[0]))

    with pytest.raises(ValueError, match="required"):
        finish_assessment(us)


def test_a_survey_without_flow_keeps_every_question_on_path_in_order(survey, qs, user):
    us = _enrol(user, survey)
    for current, following in zip(qs, qs[1:]):
        assert _advance(_answer(us, current, _first(current))).question_id == _mine(us, following).id
    assert _on_path(us) == {q.id for q in qs}


# ── should_terminate ────────────────────────────────────────────


def test_should_terminate_is_null_while_open_and_maps_stored_reasons(survey, qs, user):
    us = _enrol(user, survey)
    assert _should_terminate(us) is None

    UserSurvey.objects.filter(pk=us.pk).update(submitted_at="2026-10-06T00:00:00Z", termination_reason="time_expired")
    assert _should_terminate(us) == EndReason.FORCE_TERMINATED
    UserSurvey.objects.filter(pk=us.pk).update(termination_reason="completed")
    assert _should_terminate(us) == EndReason.FALLTHROUGH_COMPLETE
    # A row submitted before reasons were stored still reads as ended.
    UserSurvey.objects.filter(pk=us.pk).update(termination_reason=None)
    assert _should_terminate(us) == EndReason.FALLTHROUGH_COMPLETE


# ── The report migration ────────────────────────────────────────


def test_the_report_counts_open_attempts_whose_flags_would_change_and_writes_nothing(survey, qs, user, user2, capsys):
    _route(_first(qs[0]), FlowAction.GO_TO, qs[3])
    open_us = _enrol(user, survey)
    submitted = _enrol(user2, survey)
    UserAnswer.objects.create(
        user_survey=open_us, question=_mine(open_us, qs[0]), user=user
    ).selected_options.set([UserAnswerOption.objects.get(user_survey=open_us, origin_id=_first(qs[0]).id)])
    UserSurvey.objects.filter(pk=submitted.pk).update(submitted_at="2026-10-06T00:00:00Z")

    report = importlib.import_module("user_surveys.migrations.0027_report_on_path")
    report.forwards(apps, None)

    out = capsys.readouterr().out
    assert f"user_survey {open_us.id}: 2 questions off path" in out
    assert f"user_survey {submitted.id}" not in out
    assert "summary: 1 open attempts carry an edge, 1 would change, 2 flags would turn false" in out
    assert not UserQuestion.objects.filter(on_path=False).exists()
