"""Story survey-flow 2.9 — every branch is kept until the attempt ends, then pruned (`forms:AD-16`,
`forms:AD-19`).

Each transition goes through its real entry point: the `answer_question` resolver,
`should_terminate`, `finish_assessment` or the `auto_submit_expired` command.
"""

import datetime
import io

import pytest
from django.core.management import call_command
from django.utils.timezone import now

from surveys.models import AnswerSchemaOption, FlowAction, Question, Survey
from tests.test_flow_advance import (
    _answer,
    _enrol,
    _first,
    _mine,
    _on_path,
    _route,
    _second_option,
    _should_terminate,
    qs,  # noqa: F401 — the fixture
)
from user_surveys import flow, services
from user_surveys.flow import prune_off_path
from user_surveys.models import UserAnswer, UserAnswerOption, UserQuestion, UserSection, UserSurvey
from user_surveys.services import finish_assessment
from user_surveys.types import EndReason

Link = UserAnswer.selected_options.through


@pytest.fixture
def branch(qs):  # noqa: F811
    """q1's first option skips to q3, abandoning q2; its second option stays on the straight path."""
    q1 = qs[0]
    return _route(_first(q1), FlowAction.GO_TO, qs[2]), _second_option(q1)


def _stored(us, question):
    return UserAnswer.objects.filter(user_survey=us, question=_mine(us, question))


def _abandon_q2(us, qs, branch):  # noqa: F811
    """Stay, answer q2, then go back and skip: q2's answer is now on an abandoned branch."""
    skip, stay = branch
    _answer(us, qs[0], stay)
    abandoned = _answer(us, qs[1], _first(qs[1]))
    _answer(us, qs[0], skip)
    assert UserAnswer.objects.filter(pk=abandoned.pk, question__on_path=False).exists()
    assert Link.objects.filter(useranswer_id=abandoned.pk).exists()
    return abandoned


def _snapshot(us):
    return tuple(
        set(model.objects.filter(user_survey=us).values_list("pk", flat=True))
        for model in (UserQuestion, UserSection, UserAnswerOption)
    )


def _assert_pruned(us, qs, abandoned):  # noqa: F811
    assert not UserAnswer.objects.filter(pk=abandoned.pk).exists()
    assert not Link.objects.filter(useranswer_id=abandoned.pk).exists()
    assert UserQuestion.objects.filter(user_survey=us).count() == len(qs)
    assert _stored(us, qs[0]).exists()


def test_an_open_attempt_keeps_the_abandoned_branch(survey, qs, branch, user):  # noqa: F811
    us = _enrol(user, survey)
    abandoned = _abandon_q2(us, qs, branch)

    assert _should_terminate(us) is None

    assert UserSurvey.objects.get(pk=us.pk).submitted_at is None
    assert UserAnswer.objects.filter(pk=abandoned.pk, question__on_path=False).exists()
    assert Link.objects.filter(useranswer_id=abandoned.pk).exists()


def test_submit_prunes_the_abandoned_branch_and_keeps_its_question(survey, qs, branch, user):  # noqa: F811
    us = _enrol(user, survey)
    abandoned = _abandon_q2(us, qs, branch)
    for q in qs[2:]:
        _answer(us, q, _first(q))
    snapshot = _snapshot(us)

    finish_assessment(us)

    assert us.submitted_at is not None
    _assert_pruned(us, qs, abandoned)
    assert _snapshot(us) == snapshot
    assert not _mine(us, qs[1]).on_path
    assert all(_stored(us, q).exists() for q in qs[2:])


def test_a_routing_terminate_prunes_on_the_write(survey, qs, branch, user):  # noqa: F811
    _, stay = branch
    end = _route(AnswerSchemaOption.objects.create(
        schema=qs[0].answer_schema, survey_id=survey.id, question_id=qs[0].id
    ), FlowAction.TERMINATE)
    us = _enrol(user, survey)
    _answer(us, qs[0], stay)
    below = [_answer(us, q, _first(q)) for q in qs[1:3]]
    assert UserAnswer.objects.filter(pk__in=[a.pk for a in below]).count() == 2

    _answer(us, qs[0], end)

    us.refresh_from_db()
    assert us.termination_reason == UserSurvey.TERMINATION_ROUTING
    assert not UserAnswer.objects.filter(pk__in=[a.pk for a in below]).exists()
    assert UserQuestion.objects.filter(user_survey=us).count() == len(qs)
    assert _stored(us, qs[0]).exists()


def test_the_ending_threshold_prunes(survey, qs, branch, user):  # noqa: F811
    skip, _ = branch
    AnswerSchemaOption.objects.filter(pk=skip.pk).update(ending_option=True)
    Survey.objects.filter(pk=survey.pk).update(allow_end_based_on_answer_repeat=True, answers_count_to_end=1)
    us = _enrol(user, survey)
    abandoned = _abandon_q2(us, qs, branch)

    assert _should_terminate(us) == EndReason.ENDING_THRESHOLD

    assert UserSurvey.objects.get(pk=us.pk).termination_reason == UserSurvey.TERMINATION_ENDING_OPTION
    _assert_pruned(us, qs, abandoned)


def _expire(us):
    UserSurvey.objects.filter(pk=us.pk).update(started_at=now() - datetime.timedelta(hours=2))
    # Stale flags: the prune must judge against the path walked at the moment of the end.
    UserQuestion.objects.filter(user_survey=us).update(on_path=True)
    us.refresh_from_db()


@pytest.fixture
def timed(survey):
    Survey.objects.filter(pk=survey.pk).update(is_timed=True, time_limit=datetime.timedelta(minutes=5))
    return survey


def test_a_time_expiry_through_should_terminate_prunes_against_the_current_path(timed, qs, branch, user):  # noqa: F811
    us = _enrol(user, timed)
    abandoned = _abandon_q2(us, qs, branch)
    _expire(us)

    assert _should_terminate(us) == EndReason.FORCE_TERMINATED

    assert UserSurvey.objects.get(pk=us.pk).termination_reason == UserSurvey.TERMINATION_TIME_EXPIRED
    _assert_pruned(us, qs, abandoned)


def test_auto_submit_expired_prunes_against_the_current_path(timed, qs, branch, user):  # noqa: F811
    us = _enrol(user, timed)
    abandoned = _abandon_q2(us, qs, branch)
    _expire(us)

    call_command("auto_submit_expired", stdout=io.StringIO(), stderr=io.StringIO())

    assert UserSurvey.objects.get(pk=us.pk).termination_reason == UserSurvey.TERMINATION_TIME_EXPIRED
    _assert_pruned(us, qs, abandoned)


def test_a_refused_submit_deletes_nothing(survey, qs, branch, user):  # noqa: F811
    Question.objects.filter(pk=qs[2].pk).update(is_required=True)
    us = _enrol(user, survey)
    _abandon_q2(us, qs, branch)
    before = set(UserAnswer.objects.filter(user_survey=us).values_list("pk", flat=True))
    links = Link.objects.filter(useranswer_id__in=before).count()
    assert UserAnswer.objects.filter(user_survey=us, question__on_path=False).exists()

    with pytest.raises(ValueError):
        finish_assessment(us)

    assert set(UserAnswer.objects.filter(user_survey=us).values_list("pk", flat=True)) == before
    assert Link.objects.filter(useranswer_id__in=before).count() == links
    assert UserSurvey.objects.get(pk=us.pk).submitted_at is None


def test_an_answer_with_no_question_link_is_kept(survey, qs, branch, user):  # noqa: F811
    us = _enrol(user, survey)
    abandoned = _abandon_q2(us, qs, branch)
    orphan = UserAnswer.objects.create(user=user, user_survey=us, question=None, answer="x")

    finish_assessment(us)

    assert UserAnswer.objects.filter(pk=orphan.pk).exists()
    assert not UserAnswer.objects.filter(pk=abandoned.pk).exists()


def test_a_survey_without_a_flow_deletes_nothing(survey, qs, user):  # noqa: F811
    us = _enrol(user, survey)
    for q in (qs[0], *qs[2:]):
        _answer(us, q, _first(q))
    before = set(UserAnswer.objects.filter(user_survey=us).values_list("pk", flat=True))

    finish_assessment(us)

    assert set(UserAnswer.objects.filter(user_survey=us).values_list("pk", flat=True)) == before
    assert _on_path(us) == {q.id for q in qs}


def test_the_score_comes_only_from_on_path_answers(survey, qs, branch, user):  # noqa: F811
    skip, stay = branch
    AnswerSchemaOption.objects.filter(pk=skip.pk).update(score=5)
    AnswerSchemaOption.objects.filter(pk=stay.pk).update(score=1)
    AnswerSchemaOption.objects.filter(pk=_first(qs[1]).pk).update(score=100)
    for i, q in enumerate(qs[2:], start=1):
        AnswerSchemaOption.objects.filter(pk=_first(q).pk).update(score=i)
    us = _enrol(user, survey)
    abandoned = _abandon_q2(us, qs, branch)
    for q in qs[2:]:
        _answer(us, q, _first(q))

    finish_assessment(us)

    us.refresh_from_db()
    assert not UserAnswer.objects.filter(pk=abandoned.pk).exists()
    assert us.score == 5 + 1 + 2 + 3
    assert sum(UserAnswer.objects.filter(user_survey=us).values_list("score", flat=True)) == us.score


@pytest.mark.parametrize("target", ["evaluate_assessment", "publish"])
def test_a_failure_after_the_prune_rolls_the_prune_back(survey, qs, branch, user, monkeypatch, target):  # noqa: F811
    us = _enrol(user, survey)
    abandoned = _abandon_q2(us, qs, branch)

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    if target == "publish":
        monkeypatch.setattr("app.messaging.publisher.publish", boom)
    else:
        monkeypatch.setattr(services, "evaluate_assessment", boom)

    with pytest.raises(RuntimeError):
        finish_assessment(us)

    assert UserAnswer.objects.filter(pk=abandoned.pk).exists()
    assert Link.objects.filter(useranswer_id=abandoned.pk).exists()
    assert UserSurvey.objects.get(pk=us.pk).submitted_at is None


def test_prune_off_path_counts_what_it_deletes(survey, qs, branch, user):  # noqa: F811
    us = _enrol(user, survey)
    _abandon_q2(us, qs, branch)
    flow.recalculate_on_path(us)
    assert prune_off_path(us) == 1
    assert prune_off_path(us) == 0


def test_prune_off_path_deletes_nothing_without_a_flow(survey, qs, user):  # noqa: F811
    us = _enrol(user, survey)
    for q in qs:
        _answer(us, q, _first(q))
    flow.recalculate_on_path(us)
    assert prune_off_path(us) == 0
