"""Regression coverage for the attempt-allowance counters and survey results.

Both cases here came out of a QA report against the live API:

* ``usageUsed`` read ``0`` on an attempt the user had just submitted, while the
  survey card reported ``1`` for the same allowance — the attempt resolver had
  no free-tier fallback, so it only ever saw paid ``Usage`` rows.
* an unlimited grant was reported as a cap of ten, because ``usageLimit`` had
  no value meaning "no cap" and fell back to ``FREE_ATTEMPTS``.

The submitted-attempt cases here set ``submitted_at`` directly rather than going
through ``finish_assessment``; see ``test_submit_keeps_questions`` for coverage
of the real submit path.
"""

import uuid

import pytest
from django.core.exceptions import ValidationError
from django.utils.timezone import now

from surveys.models import Usage
from surveys.usage_access import FREE_ATTEMPTS
from user_surveys.services import enroll_user_in_assessment


USER_SURVEY_QUERY = """
query Attempts($input: UserSurveysListInput!) {
  userSurvey(userSurveysListInput: $input) {
    total
    items {
      id
      submittedAt
      usageUsed
      usageLimit
      sections {
        id
        isHidden
        questions { id }
      }
    }
  }
}
"""


class _Identity:
    def __init__(self, user):
        self.subject_str = user.id
        self.email_str = user.email
        self.preferred_username = user.username
        self.first_name = ""
        self.last_name = ""


class _Context:
    """The slice of the GraphQL context these resolvers actually read."""

    def __init__(self, user):
        self.request = None
        self.identity = _Identity(user)
        self.auth_context = None
        self.currency = None


def _run(query, user, **variables):
    from surveys import schema as schema_module

    result = schema_module.schema.execute_sync(
        query, variable_values=variables or None, context_value=_Context(user)
    )
    assert result.errors is None, result.errors
    return result.data


def _attempts(user):
    data = _run(USER_SURVEY_QUERY, user, input={"limit": 50, "offset": 0})
    return data["userSurvey"]["items"]


def _submit(user_survey):
    user_survey.submitted_at = now()
    user_survey.evaluated_at = now()
    user_survey.save(update_fields=["submitted_at", "evaluated_at"])
    return user_survey


# ── usageUsed ────────────────────────────────────────────────────────

def test_usage_used_counts_a_submitted_attempt_on_the_free_tier(user, survey, section):
    """The reported defect: a consumed attempt read back as 0 of 10.

    A free-tier attempt writes no ``Usage`` row, so the submitted snapshot is
    the only evidence it was spent.
    """
    _submit(enroll_user_in_assessment(user, survey.id)[0])

    attempt = _attempts(user)[0]
    assert attempt["usageUsed"] == 1
    assert attempt["usageLimit"] == FREE_ATTEMPTS


def test_usage_used_ignores_an_attempt_still_in_progress(user, survey, section):
    enroll_user_in_assessment(user, survey.id)

    attempt = _attempts(user)[0]
    assert attempt["usageUsed"] == 0
    assert attempt["usageLimit"] == FREE_ATTEMPTS


def test_the_attempt_and_the_survey_card_report_the_same_number(user, survey, section):
    """The two surfaces the QA report found disagreeing."""
    from surveys.types.survey import SurveyType

    _submit(enroll_user_in_assessment(user, survey.id)[0])

    class _Info:
        context = None

    info = _Info()
    info.context = _Context(user)

    attempt = _attempts(user)[0]
    assert attempt["usageUsed"] == SurveyType.usage_used(survey, info) == 1
    assert attempt["usageLimit"] == SurveyType.usage_limit(survey, info) == FREE_ATTEMPTS


def test_usage_rows_win_over_the_free_tier_count(user, survey, section):
    """A purchased allowance replaces the free one rather than adding to it."""
    _submit(enroll_user_in_assessment(user, survey.id)[0])
    Usage.objects.create(
        user=user, survey=survey, order_id="order-1", usage_limit=5, used_count=3
    )

    attempt = _attempts(user)[0]
    assert attempt["usageUsed"] == 3
    assert attempt["usageLimit"] == 5


def test_usage_used_agrees_with_the_gate_that_blocks_enrolment(user, survey, section):
    """The counter and the enrolment gate read the same source of truth, so the
    user is blocked exactly when the display says the allowance is spent."""
    for _ in range(FREE_ATTEMPTS):
        _submit(enroll_user_in_assessment(user, survey.id)[0])

    attempts = _attempts(user)
    assert len(attempts) == FREE_ATTEMPTS
    assert all(item["usageUsed"] == FREE_ATTEMPTS for item in attempts)

    from user_surveys.schemas.mutations.enroll_assessment import EnrollAssessmentMutation

    class _Info:
        context = None

    info = _Info()
    info.context = _Context(user)
    with pytest.raises(ValidationError):
        EnrollAssessmentMutation().enroll_assessment(info, survey_id=survey.id)


def test_usage_used_is_scoped_to_the_child_the_attempt_was_taken_for(user, survey, section):
    """Each child carries their own free allowance — which is how the enrolment
    gate counts — so one child's attempts must not show up on another's."""
    from accounts.models import Child

    survey.is_for_child = True
    survey.save(update_fields=["is_for_child"])

    first = Child.objects.create(id=str(uuid.uuid4()), name="First")
    second = Child.objects.create(id=str(uuid.uuid4()), name="Second")

    _submit(enroll_user_in_assessment(user, survey.id, child=first)[0])
    _submit(enroll_user_in_assessment(user, survey.id, child=first)[0])
    _submit(enroll_user_in_assessment(user, survey.id, child=second)[0])

    by_child = {}
    from user_surveys.models import UserSurvey

    for item in _attempts(user):
        child_id = UserSurvey.objects.get(pk=item["id"]).child_id
        by_child.setdefault(child_id, set()).add(item["usageUsed"])

    assert by_child == {first.id: {2}, second.id: {1}}


# ── unlimited grants ─────────────────────────────────────────────────

def test_an_unlimited_grant_reports_a_null_limit_rather_than_a_cap_of_ten(user, survey, section):
    """The reported defect: `usageLimit` could not express "no cap".

    An unlimited grant carries `usage_limit = 0`, which the `or FREE_ATTEMPTS`
    fallback turned into 10, so a client gating on `usageUsed < usageLimit`
    refused the 11th attempt. `null` is that missing value.
    """
    _submit(enroll_user_in_assessment(user, survey.id)[0])
    Usage.objects.create(
        user=user, survey=survey, order_id="order-1", usage_limit=0, used_count=11
    )

    attempt = _attempts(user)[0]
    assert attempt["usageLimit"] is None
    assert attempt["usageUsed"] == 11


def test_a_capped_grant_still_reports_its_number(user, survey, section):
    _submit(enroll_user_in_assessment(user, survey.id)[0])
    Usage.objects.create(
        user=user, survey=survey, order_id="order-1", usage_limit=5, used_count=1
    )

    assert _attempts(user)[0]["usageLimit"] == 5


def test_the_free_tier_is_a_real_cap_not_an_unlimited_grant(user, survey, section):
    """A user with no usage rows is capped at FREE_ATTEMPTS. That is a number,
    not `null` — the two must not collapse into each other."""
    _submit(enroll_user_in_assessment(user, survey.id)[0])

    assert _attempts(user)[0]["usageLimit"] == FREE_ATTEMPTS


def test_the_server_already_lets_an_unlimited_user_past_the_free_cap(user, survey, section):
    """Confirms the block was only ever client-side: the enrolment gate honours
    an uncapped grant, so the null limit closes the gap without changing what
    the server enforces."""
    for _ in range(FREE_ATTEMPTS):
        _submit(enroll_user_in_assessment(user, survey.id)[0])
    Usage.objects.create(
        user=user, survey=survey, order_id="order-1", usage_limit=0, used_count=FREE_ATTEMPTS
    )

    from user_surveys.schemas.mutations.enroll_assessment import EnrollAssessmentMutation

    class _Info:
        context = None

    info = _Info()
    info.context = _Context(user)
    eleventh = EnrollAssessmentMutation().enroll_assessment(info, survey_id=survey.id)
    assert eleventh.submitted_at is None


def test_the_survey_card_and_the_attempt_agree_on_unlimited(user, survey, section):
    from surveys.types.survey import SurveyType

    _submit(enroll_user_in_assessment(user, survey.id)[0])
    Usage.objects.create(
        user=user, survey=survey, order_id="order-1", usage_limit=0, used_count=3
    )

    class _Info:
        context = None

    info = _Info()
    info.context = _Context(user)
    assert _attempts(user)[0]["usageLimit"] is SurveyType.usage_limit(survey, info) is None


# ── submitted results ────────────────────────────────────────────────

def test_a_submitted_attempt_still_returns_its_sections(user, survey, section, question):
    """Submitting must not empty out the snapshot the results page renders."""
    user_survey, _ = enroll_user_in_assessment(user, survey.id)
    before = {item["id"] for item in _attempts(user)[0]["sections"]}
    assert before

    _submit(user_survey)

    attempt = _attempts(user)[0]
    assert attempt["submittedAt"] is not None
    assert {item["id"] for item in attempt["sections"]} == before
    assert all(item["questions"] for item in attempt["sections"])


def test_hidden_sections_are_returned_and_flagged_rather_than_dropped(user, survey, section):
    """The results page needs the section to decide how to render it; filtering
    it out server-side is what would produce an empty ``sections`` list."""
    user_survey, _ = enroll_user_in_assessment(user, survey.id)
    snapshot_section = user_survey.sections.first()
    snapshot_section.is_hidden = True
    snapshot_section.save(update_fields=["is_hidden"])
    _submit(user_survey)

    sections = _attempts(user)[0]["sections"]
    assert [item["isHidden"] for item in sections] == [True]
