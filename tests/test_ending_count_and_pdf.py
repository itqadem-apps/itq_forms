"""survey-flow 2.9 follow-ups — the ending count follows the path, the PDF shows only on-path
answers, and time running out during an answer write is pinned (`forms:AD-7`, `forms:AD-17`,
`forms:AD-19`).

Every write goes through the real `answer_question` resolver and every end through
`should_terminate`; the PDF is read off the template context it renders from.
"""

import datetime

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils.timezone import now

from surveys.models import AnswerSchemaOption, FlowAction, Question, Survey
from surveys.question_order import renumber_questions
from user_surveys.models import UserAnswer, UserAnswerOption, UserQuestion, UserSurvey
from user_surveys.pdf_service import _build_context
from user_surveys.schemas.mutations.answer_question import AnswerQuestionMutation
from user_surveys.schemas.queries.should_terminate import ShouldTerminateQuery
from user_surveys.services import enroll_user_in_assessment
from user_surveys.types import EndReason


def _resolver(cls, name):
    field = next(f for f in cls.__strawberry_definition__.fields if f.python_name == name)
    fn = field.base_resolver.wrapped_func
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def _question(survey, title, q_type=Question.QUESTION_TYPE_RADIO_MCQ):
    return Question.objects.create(survey=survey, section=None, title=title, type=q_type)


def _first(question):
    return question.answer_schema.options.order_by("id").first()


def _second_option(question):
    return AnswerSchemaOption.objects.create(
        schema=question.answer_schema, survey_id=question.survey_id, question_id=question.id
    )


def _route(option, action, target=None, **extra):
    AnswerSchemaOption.objects.filter(pk=option.pk).update(flow_action=action, flow_target=target, **extra)
    return option


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


def _should_terminate(us):
    return _resolver(ShouldTerminateQuery, "should_terminate")(
        ShouldTerminateQuery(), None, user_survey_id=str(us.id), django_user=us.user
    )


def _count(us):
    return UserSurvey.objects.get(pk=us.pk).count_of_ending_options


@pytest.fixture
def qs(survey):
    """q1..q5, sectionless, in order. Each first option is an ending option and each question has a
    second, non-ending one."""
    questions = [_question(survey, f"q{i}") for i in range(1, 6)]
    renumber_questions(survey.id, [q.id for q in questions])
    for q in questions:
        AnswerSchemaOption.objects.filter(pk=_first(q).pk).update(ending_option=True)
        _second_option(q)
    return questions


def _ending(q):
    return _first(q)


def _plain(q):
    return q.answer_schema.options.order_by("id").last()


def _feature(survey, in_row=False, to_end=0):
    Survey.objects.filter(pk=survey.pk).update(
        allow_end_based_on_answer_repeat=True,
        end_based_on_answer_repeat_in_row=in_row,
        answers_count_to_end=to_end,
    )


# ── The count follows the path ──────────────────────────────────


def test_total_mode_counts_every_on_path_ending_answer(survey, qs, user):
    _feature(survey)
    us = _enrol(user, survey)
    _answer(us, qs[0], _ending(qs[0]))
    _answer(us, qs[1], _ending(qs[1]))
    assert _count(us) == 2


def test_re_answering_with_an_ending_option_counts_once(survey, qs, user):
    _feature(survey)
    us = _enrol(user, survey)
    _answer(us, qs[0], _ending(qs[0]))
    _answer(us, qs[0], _ending(qs[0]))
    assert _count(us) == 1


def test_going_back_to_a_non_ending_option_uncounts_it(survey, qs, user):
    _feature(survey)
    us = _enrol(user, survey)
    _answer(us, qs[0], _ending(qs[0]))
    _answer(us, qs[0], _plain(qs[0]))
    assert _count(us) == 0


def test_an_ending_answer_the_new_branch_leaves_off_the_path_is_not_counted(survey, qs, user):
    _feature(survey)
    skip = _route(_plain(qs[0]), FlowAction.GO_TO, qs[2])
    us = _enrol(user, survey)
    _answer(us, qs[0], _ending(qs[0]))
    _answer(us, qs[1], _ending(qs[1]))
    assert _count(us) == 2

    _answer(us, qs[0], skip)

    assert not _mine(us, qs[1]).on_path
    assert UserAnswer.objects.filter(user_survey=us, question=_mine(us, qs[1])).exists()
    assert _count(us) == 0


def test_in_row_mode_resets_at_a_non_ending_answer(survey, qs, user):
    _feature(survey, in_row=True)
    us = _enrol(user, survey)
    _answer(us, qs[0], _ending(qs[0]))
    _answer(us, qs[1], _ending(qs[1]))
    _answer(us, qs[2], _plain(qs[2]))
    _answer(us, qs[3], _ending(qs[3]))
    assert _count(us) == 1


def test_in_row_mode_follows_path_order_not_write_order(survey, qs, user):
    _feature(survey, in_row=True)
    us = _enrol(user, survey)
    # Accumulated in write order this would end at 0; along the path it is E, N, E.
    _answer(us, qs[2], _ending(qs[2]))
    _answer(us, qs[0], _ending(qs[0]))
    _answer(us, qs[1], _plain(qs[1]))
    assert _count(us) == 1


def test_in_row_mode_free_input_neither_adds_nor_resets(survey, qs, user):
    text = _question(survey, "free", q_type=Question.QUESTION_TYPE_TEXT)
    renumber_questions(survey.id, [qs[0].id, text.id, *(q.id for q in qs[1:])])
    _feature(survey, in_row=True)
    us = _enrol(user, survey)
    _answer(us, qs[0], _ending(qs[0]))
    _answer(us, text, text="anything")
    _answer(us, qs[1], _ending(qs[1]))
    assert _count(us) == 2


def _checkbox(survey, qs, position):
    """A checkbox question inserted at `position`, with two ending options and one non-ending."""
    box = _question(survey, "box", q_type=Question.QUESTION_TYPE_CHECKBOX_MCQ)
    order = [q.id for q in qs]
    order.insert(position, box.id)
    renumber_questions(survey.id, order)
    AnswerSchemaOption.objects.filter(pk=_first(box).pk).update(ending_option=True)
    second = _second_option(box)
    AnswerSchemaOption.objects.filter(pk=second.pk).update(ending_option=True)
    _second_option(box)
    return box


def _answer_many(us, question, options):
    uq = _mine(us, question)
    assert uq.type == UserQuestion.TYPE_CHECKBOX
    values = [str(UserAnswerOption.objects.get(user_survey=us, origin_id=o.id).id) for o in options]
    return _resolver(AnswerQuestionMutation, "answer_question")(
        AnswerQuestionMutation(), None, user_survey_id=str(us.id), question_id=str(uq.id),
        answer=values, django_user=us.user,
    )


def test_total_mode_counts_each_ending_option_one_checkbox_answer_selects(survey, qs, user):
    box = _checkbox(survey, qs, 0)
    _feature(survey)
    us = _enrol(user, survey)
    first, second, _ = box.answer_schema.options.order_by("id")

    _answer_many(us, box, [first, second])

    assert _count(us) == 2


def test_in_row_mode_a_checkbox_answer_with_an_ending_option_adds_and_does_not_reset(survey, qs, user):
    box = _checkbox(survey, qs, 1)
    _feature(survey, in_row=True)
    us = _enrol(user, survey)
    ending, _, plain = box.answer_schema.options.order_by("id")

    _answer(us, qs[0], _ending(qs[0]))
    _answer_many(us, box, [ending, plain])

    assert _count(us) == 2


def test_with_the_feature_off_the_count_is_untouched_and_not_queried(survey, qs, user):
    us = _enrol(user, survey)
    UserSurvey.objects.filter(pk=us.pk).update(count_of_ending_options=5)

    with CaptureQueriesContext(connection) as ctx:
        _answer(us, qs[0], _ending(qs[0]))

    assert _count(us) == 5
    through = UserAnswer.selected_options.through._meta.db_table
    assert not [q for q in ctx.captured_queries if through in q["sql"] and "ending_option" in q["sql"]]


def test_the_threshold_ends_the_attempt_and_its_answers_survive_the_prune(survey, qs, user):
    _feature(survey, to_end=2)
    us = _enrol(user, survey)
    first = _answer(us, qs[0], _ending(qs[0]))
    second = _answer(us, qs[1], _ending(qs[1]))

    assert _should_terminate(us) == EndReason.ENDING_THRESHOLD

    us.refresh_from_db()
    assert us.submitted_at is not None and us.termination_reason == UserSurvey.TERMINATION_ENDING_OPTION
    assert UserAnswer.objects.filter(pk__in=[first.pk, second.pk]).count() == 2


def test_the_threshold_is_not_reached_after_going_back(survey, qs, user):
    _feature(survey, to_end=2)
    us = _enrol(user, survey)
    _answer(us, qs[0], _ending(qs[0]))
    _answer(us, qs[1], _ending(qs[1]))
    _answer(us, qs[1], _plain(qs[1]))

    assert _should_terminate(us) is None
    assert UserSurvey.objects.get(pk=us.pk).submitted_at is None


# ── The PDF lists only on-path answers ──────────────────────────


def _skip_to_q3(qs):
    """Before enrolment: q1's non-ending option skips q2."""
    return _route(_plain(qs[0]), FlowAction.GO_TO, qs[2])


def _abandon_q2(us, qs, skip):
    """Stay, answer q2, then go back and skip it: q2's answer stays stored, off the path."""
    _answer(us, qs[0], _ending(qs[0]))
    abandoned = _answer(us, qs[1], _ending(qs[1]))
    _answer(us, qs[0], skip)
    assert UserAnswer.objects.filter(pk=abandoned.pk, question__on_path=False).exists()
    return abandoned


def test_the_pdf_of_an_old_attempt_lists_only_on_path_answers(survey, qs, user):
    skip = _skip_to_q3(qs)
    us = _enrol(user, survey)
    _abandon_q2(us, qs, skip)
    _answer(us, qs[2], _ending(qs[2]))
    # Submitted before 2.9: never pruned, so the abandoned answer is still stored.
    UserSurvey.objects.filter(pk=us.pk).update(submitted_at=now(), termination_reason=UserSurvey.TERMINATION_COMPLETED)
    us.refresh_from_db()

    context = _build_context(us)

    assert [a["question_title"] for a in context["answers"]] == ["q1", "q3"]
    assert [a["number"] for a in context["answers"]] == ["01", "02"]
    assert context["total_questions"] == 2


def test_the_pdf_keeps_an_answer_with_no_question(survey, qs, user):
    us = _enrol(user, survey)
    _answer(us, qs[0], _ending(qs[0]))
    UserAnswer.objects.create(user_survey=us, user=user, question=None, answer="orphan")

    context = _build_context(us)

    assert context["total_questions"] == 2


# ── Time running out during an answer write ─────────────────────


def test_expiry_mid_write_refuses_and_leaves_the_finish_to_should_terminate(survey, qs, user):
    Survey.objects.filter(pk=survey.pk).update(is_timed=True, time_limit=datetime.timedelta(minutes=5))
    skip = _skip_to_q3(qs)
    us = _enrol(user, survey)
    abandoned = _abandon_q2(us, qs, skip)
    before = set(UserAnswer.objects.filter(user_survey=us).values_list("pk", flat=True))
    UserSurvey.objects.filter(pk=us.pk).update(started_at=now() - datetime.timedelta(hours=2))

    with pytest.raises(ValidationError, match="Time has expired"):
        _answer(us, qs[2], _ending(qs[2]))

    us.refresh_from_db()
    assert us.submitted_at is None and us.termination_reason is None
    assert set(UserAnswer.objects.filter(user_survey=us).values_list("pk", flat=True)) == before

    assert _should_terminate(us) == EndReason.FORCE_TERMINATED

    us.refresh_from_db()
    assert us.submitted_at is not None and us.termination_reason == UserSurvey.TERMINATION_TIME_EXPIRED
    assert not UserAnswer.objects.filter(pk=abandoned.pk).exists()
    assert set(UserAnswer.objects.filter(user_survey=us).values_list("pk", flat=True)) == before - {abandoned.pk}
