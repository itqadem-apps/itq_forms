"""Regression coverage for BUG-121 — ids handed out as `ID`, accepted as `Int!`.

Every model pk this service exposes comes back as GraphQL `ID`, which is a
string. The mutations and queries declared their id arguments as `Int!`, so a
client that read `question.id` from us and passed it straight back was rejected
every time with "Int cannot represent non-integer value". `UserSurveyType.id`
is one of the handful declared `int`, which is why `answerQuestion` accepted
`userSurveyId` and refused `questionId` in the same request — the mismatch
looked like a working pattern because half of it was.

These tests pin both directions: the string a client actually receives, and the
integer literal older callers send.
"""

import pytest

from user_surveys.models import UserAnswer
from user_surveys.services import enroll_user_in_assessment

from .test_submit_keeps_questions import (
    ANSWER,
    FINISH,
    _build_survey,
    _run,
    _snapshot_questions,
)


pytestmark = pytest.mark.django_db


def test_a_question_id_read_from_the_api_is_accepted_verbatim(user, survey):
    """The reported defect. `UserQuestionType.id` serializes as a string, so
    this is the exact value a client holds after reading the survey."""
    _build_survey(survey, sections=1, per_section=2)
    user_survey, _ = enroll_user_in_assessment(user, survey.id)
    question = _snapshot_questions(user_survey)[0]
    option = question.answer_schema.options.first()

    payload = _run(
        user, ANSWER,
        us=str(user_survey.id), q=str(question.id), a=[str(option.id)],
    )["answerQuestion"]

    assert payload["__typename"] == "UserAnswerType", payload
    assert UserAnswer.objects.filter(user_survey=user_survey, question=question).exists()


def test_integer_ids_still_work(user, survey):
    """`ID` coerces integer literals too, so callers that were already passing
    numbers — every client written against the old `Int!` signature — keep
    working without a change."""
    _build_survey(survey, sections=1, per_section=2)
    user_survey, _ = enroll_user_in_assessment(user, survey.id)
    question = _snapshot_questions(user_survey)[0]
    option = question.answer_schema.options.first()

    payload = _run(
        user, ANSWER,
        us=user_survey.id, q=question.id, a=[str(option.id)],
    )["answerQuestion"]

    assert payload["__typename"] == "UserAnswerType", payload


def test_a_non_numeric_id_is_a_client_error_not_a_lookup_miss(user, survey):
    """`ID` accepts any string, so garbage now reaches the resolver where `Int!`
    used to reject it at validation. It must not be reported as "not found" —
    that reads as a deleted question rather than a malformed request."""
    _build_survey(survey, sections=1, per_section=2)
    user_survey, _ = enroll_user_in_assessment(user, survey.id)

    payload = _run(
        user, ANSWER, us=str(user_survey.id), q="not-a-number", a=["1"],
    )["answerQuestion"]

    assert payload["__typename"] == "OperationInfo", payload
    assert "Invalid id" in payload["messages"][0]["message"]


def test_the_whole_answer_and_submit_round_trip_runs_on_string_ids(user, survey):
    """End to end on the ids as the client actually holds them — the mobile
    runner's flow, which failed on every single answer before this."""
    _build_survey(survey, sections=1, per_section=2)
    user_survey, _ = enroll_user_in_assessment(user, survey.id)
    questions = _snapshot_questions(user_survey)

    for question in questions:
        option = question.answer_schema.options.first()
        _run(user, ANSWER, us=str(user_survey.id), q=str(question.id), a=[str(option.id)])
    _run(user, FINISH, us=str(user_survey.id))

    assert UserAnswer.objects.filter(user_survey=user_survey).count() == len(questions)


# ── userSurvey id filters ───────────────────────────────────────────
#
# The listing ran every filter ending in ``_id`` through ``as_pk``. That is
# right for ``id``, ``surveyId`` and ``collectionId``, which name integer pks,
# and wrong for ``childId`` and ``userId``: ``accounts.Child`` and
# ``accounts.User`` are keyed by the string ids ``itq_users`` issues, so a real
# child id could never pass ``int()`` and every child-filtered request failed
# with "Invalid id".

ATTEMPTS = """
query Attempts($input: UserSurveysListInput!) {
  userSurvey(userSurveysListInput: $input) { total items { id } }
}
"""


def _attempt_ids(user, **filters):
    from .test_usage_and_results import _run as _query

    data = _query(ATTEMPTS, user, input={"limit": 50, "offset": 0, "filters": filters})
    return {int(item["id"]) for item in data["userSurvey"]["items"]}


def _for_child(user, survey, child):
    return enroll_user_in_assessment(user, survey.id, child=child)[0]


def test_child_id_filter_takes_the_string_id_a_child_actually_has(user, survey, section):
    """The defect behind the child profile's missing tab: ``childId`` is a
    UUID, and it must select that child's rows — not another child's, and not
    the caller's own adult attempts."""
    import uuid

    from accounts.models import Child
    from user_surveys.models import UserSurvey

    survey.is_for_child = True
    survey.save(update_fields=["is_for_child"])
    first = Child.objects.create(id=str(uuid.uuid4()), name="First")
    second = Child.objects.create(id=str(uuid.uuid4()), name="Second")

    mine = {_for_child(user, survey, first).id, _for_child(user, survey, first).id}
    _for_child(user, survey, second)
    # A child-only survey refuses an adult enrolment, so the caller's own
    # adult attempt is written directly.
    UserSurvey.objects.create(user=user, survey=survey, child=None)

    assert _attempt_ids(user, childId=first.id) == mine


def test_user_id_filter_takes_the_string_id_a_user_actually_has(user, survey, section):
    """Same shape, same fault: ``accounts.User`` is keyed by the identity
    provider's subject, never an integer."""
    attempt = enroll_user_in_assessment(user, survey.id)[0]

    assert _attempt_ids(user, userId=user.id) == {attempt.id}


@pytest.mark.parametrize("field", ["id", "surveyId", "collectionId"])
def test_integer_id_filters_still_reject_a_non_integer(user, field):
    """Only the string-keyed filters stopped being coerced. The integer ones
    still refuse garbage as a malformed request rather than an empty page."""
    from surveys import schema as schema_module

    from .test_usage_and_results import _Context

    result = schema_module.schema.execute_sync(
        ATTEMPTS,
        variable_values={"input": {"filters": {field: "not-a-number"}}},
        context_value=_Context(user),
    )

    assert result.errors, result.data
    assert "Invalid id" in result.errors[0].message
