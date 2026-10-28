"""A hand-marked attempt reaches itq_courses in two events: `SurveyResponseSubmitted` says the grade
is still to come (`awaiting_evaluation`), and `SurveyResponseEvaluated` carries the marked score,
again on every re-mark. Courses keeps the learner's first attempt, so the event says if it is one."""

import json
from datetime import timedelta
from unittest.mock import patch

from django.utils.timezone import now

from surveys.models import Survey
from user_surveys.models import UserSurvey
from user_surveys.services import finish_assessment, is_first_attempt, publish_evaluated

from tests.test_action_materials import _Context
from tests.test_score_basis import _enrol, _pick, _scored, qs  # noqa: F401

EVALUATE = """
mutation Evaluate($id: ID!, $override: Int) {
  evaluateManualAssessment(userSurveyId: $id, scoreOverride: $override) { ... on FinishAssessmentResult { status score } ... on OperationInfo { messages { message } } }
}
"""


def _capture():
    captured = []
    return captured, patch(
        "app.messaging.publisher._outbox.add", side_effect=lambda **kw: captured.append(kw)
    )


def _payloads(captured, event_type):
    rows = [row["payload"] for row in captured if row["event_type"] == event_type]
    for row in rows:
        json.dumps(row)
    return rows


def _manual(survey):
    Survey.objects.filter(pk=survey.pk).update(evaluation_type=Survey.EVALUATION_TYPE_MANUAL_EVALUATION)


def _submitted(user, survey, qs):
    us = _enrol(user, survey)
    _pick(us, qs[0])
    captured, patcher = _capture()
    with patcher:
        finish_assessment(us)
    us.refresh_from_db()
    return us, captured


def _evaluate(user, us, override=None):
    from surveys import schema as schema_module

    captured, patcher = _capture()
    with patcher:
        result = schema_module.schema.execute_sync(
            EVALUATE,
            variable_values={"id": str(us.id), "override": override},
            context_value=_Context(user),
        )
    assert result.errors is None, result.errors
    return _payloads(captured, "SurveyResponseEvaluated")


def test_a_hand_marked_submission_says_its_grade_is_to_come(user, survey, qs):
    _scored(qs[0], 10)
    _manual(survey)
    _, captured = _submitted(user, survey, qs)
    [payload] = _payloads(captured, "SurveyResponseSubmitted")
    assert payload["awaiting_evaluation"] is True
    assert payload["score"] is None


def test_an_automatic_submission_is_not_awaiting(user, survey, qs):
    _scored(qs[0], 10)
    _, captured = _submitted(user, survey, qs)
    [payload] = _payloads(captured, "SurveyResponseSubmitted")
    assert payload["awaiting_evaluation"] is False


def test_an_unscored_hand_marked_submission_is_not_awaiting(user, survey, qs):
    _manual(survey)
    Survey.objects.filter(pk=survey.pk).update(use_score=False)
    _, captured = _submitted(user, survey, qs)
    [payload] = _payloads(captured, "SurveyResponseSubmitted")
    assert payload["awaiting_evaluation"] is False


def test_marking_publishes_the_score_and_a_re_mark_publishes_again(user, survey, qs):
    _scored(qs[0], 10)
    _scored(qs[1], 0, 40)
    _manual(survey)
    us, _ = _submitted(user, survey, qs)

    [first] = _evaluate(user, us)
    assert (first["user_survey_id"], first["score"], first["first_attempt"]) == (us.id, 10, True)
    assert first["max_score"] > 0
    assert first["evaluated_at"] is not None

    [again] = _evaluate(user, us, override=7)
    assert again["score"] == 7


def test_a_later_attempt_is_not_the_first(user, survey, qs):
    first = _enrol(user, survey)
    second = UserSurvey.objects.get(pk=first.pk)
    second.pk = None
    second.save()
    at = now()
    UserSurvey.objects.filter(pk=first.pk).update(submitted_at=at)
    UserSurvey.objects.filter(pk=second.pk).update(submitted_at=at + timedelta(minutes=5))
    first.refresh_from_db()
    second.refresh_from_db()
    assert is_first_attempt(first) is True
    assert is_first_attempt(second) is False


def test_the_regrade_apply_can_say_first_attempt_itself(user, survey, qs):
    _scored(qs[0], 10)
    us, _ = _submitted(user, survey, qs)
    captured, patcher = _capture()
    with patcher:
        publish_evaluated(us, first_attempt=True)
    [payload] = _payloads(captured, "SurveyResponseEvaluated")
    assert payload["first_attempt"] is True
    assert payload["score"] == us.score
