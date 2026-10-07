"""Story survey-flow 2.7 — score basis is declared per assessment (`forms:AD-10`, `forms:AD-16`,
`forms:AD-17`)."""

import pytest
from django.core.exceptions import ValidationError
from django.utils.timezone import now

from surveys.models import AnswerSchemaOption, FlowAction, Question, ScoreBasis, Survey
from surveys.question_order import renumber_questions
from surveys.schemas.mutations.surveys import _check_score_basis
from user_surveys.models import UserAnswer, UserAnswerOption, UserQuestion, UserSurvey
from user_surveys.pdf_service import _build_context
from user_surveys.services import enroll_user_in_assessment, evaluate_assessment, finish_assessment, max_score

from conftest import ORG
from pkg_auth.authorization import AuthContext, OrgId, UserId
from tests.test_action_materials import _Context, _evaluate
from tests.test_flow_advance import _answer


def _scored(question, *scores):
    question.answer_schema.options.all().delete()
    return [
        AnswerSchemaOption.objects.create(
            schema=question.answer_schema, survey_id=question.survey_id, question_id=question.id, score=s
        )
        for s in scores
    ]


@pytest.fixture
def qs(survey):
    """q1..q3, sectionless radios, each with one option scoring 30."""
    questions = [
        Question.objects.create(survey=survey, section=None, title=f"q{i}", type=Question.QUESTION_TYPE_RADIO_MCQ)
        for i in (1, 2, 3)
    ]
    renumber_questions(survey.id, [q.id for q in questions])
    for q in questions:
        _scored(q, 30)
    return questions


def _enrol(user, survey, basis=None):
    if basis is not None:
        Survey.objects.filter(pk=survey.pk).update(score_basis=basis)
    us, _ = enroll_user_in_assessment(user, survey.id)
    return us


def _mine(us, question):
    return UserQuestion.objects.get(user_survey=us, origin_id=question.id)


def _pick(us, question, option=None):
    uq = _mine(us, question)
    answer = UserAnswer.objects.create(user=us.user, question=uq, user_survey=us, type=uq.type)
    chosen = option or question.answer_schema.options.first()
    answer.selected_options.set([UserAnswerOption.objects.get(user_survey=us, origin_id=chosen.id)])
    return answer


def _off_path(us, question):
    UserQuestion.objects.filter(pk=_mine(us, question).pk).update(on_path=False)


def _max_score_field(user, us):
    from surveys import schema as schema_module

    result = schema_module.schema.execute_sync(
        """query R($input: UserSurveysListInput!) {
          userSurvey(userSurveysListInput: $input) { items { score maxScore scoreBasis } }
        }""",
        variable_values={"input": {"limit": 1, "offset": 0, "filters": {"id": us.id}, "sort": None}},
        context_value=_Context(user),
    )
    assert result.errors is None, result.errors
    return result.data["userSurvey"]["items"][0]


# ── The setting ──────────────────────────────────────────────────────


def test_the_basis_defaults_to_reached_and_is_snapshotted(user, survey, qs):
    assert Survey.objects.get(pk=survey.pk).score_basis == ScoreBasis.REACHED
    assert _enrol(user, survey, ScoreBasis.ALL).score_basis == "all"


def test_an_unknown_basis_is_refused():
    _check_score_basis({"score_basis": "answered"})
    _check_score_basis({})
    with pytest.raises(ValidationError) as err:
        _check_score_basis({"score_basis": "x"})
    assert "score_basis" in err.value.message_dict
    # A sent null would reach the NOT NULL column.
    with pytest.raises(ValidationError):
        _check_score_basis({"score_basis": None})


# ── The matrix ───────────────────────────────────────────────────────


def test_no_flow_at_the_default_scores_as_today(user, survey, qs):
    us = _enrol(user, survey)
    _pick(us, qs[0])
    _pick(us, qs[1])
    evaluate_assessment(us)
    us.refresh_from_db()
    assert us.score == 60
    assert max_score(us) == 90
    assert _max_score_field(user, us) == {"score": 60, "maxScore": 90, "scoreBasis": "reached"}


def test_reached_drops_a_skipped_question_from_the_max(user, survey, qs):
    us = _enrol(user, survey)
    _off_path(us, qs[1])
    assert max_score(us) == 60


def test_all_keeps_a_skipped_question_in_the_max(user, survey, qs):
    us = _enrol(user, survey, ScoreBasis.ALL)
    _off_path(us, qs[1])
    assert max_score(us) == 90


def test_answered_drops_an_unanswered_question_on_the_path(user, survey, qs):
    us = _enrol(user, survey, ScoreBasis.ANSWERED)
    _pick(us, qs[0])
    _pick(us, qs[1])
    UserAnswer.objects.create(user=user, question=_mine(us, qs[2]), user_survey=us, type="radio")
    assert max_score(us) == 60


@pytest.mark.parametrize("basis", ScoreBasis.values)
def test_an_abandoned_branch_answer_never_scores(user, survey, qs, basis):
    us = _enrol(user, survey, basis)
    for q in qs:
        _pick(us, q)
    _off_path(us, qs[1])
    evaluate_assessment(us)
    us.refresh_from_db()
    assert us.score == 60


def test_scoring_off_has_no_max(user, survey, qs):
    Survey.objects.filter(pk=survey.pk).update(use_score=False)
    us = _enrol(user, survey)
    assert _max_score_field(user, us)["maxScore"] is None


def test_the_per_question_max_follows_the_pdf_rule(user, survey, qs):
    _scored(qs[0], 5, 20, -3)
    qs[1].type = Question.QUESTION_TYPE_CHECKBOX_MCQ
    qs[1].save(update_fields=["type"])
    _scored(qs[1], 5, 20, -3)
    us = _enrol(user, survey, ScoreBasis.ALL)
    assert max_score(us) == 20 + 25 + 30


# ── Paths the flow decides ───────────────────────────────────────────


@pytest.fixture
def branched(survey, qs):
    """q1: `skip` (10) goes to q3, `stay` (0) falls through to q2."""
    skip, stay = _scored(qs[0], 10, 0)
    AnswerSchemaOption.objects.filter(pk=skip.pk).update(flow_action=FlowAction.GO_TO, flow_target=qs[2])
    return skip, stay


def test_a_force_terminated_attempt_honours_the_basis(user, survey, qs, branched):
    skip, stay = branched
    us = _enrol(user, survey)
    _answer(us, qs[0], stay)
    _answer(us, qs[1], qs[1].answer_schema.options.first())
    _answer(us, qs[0], skip)
    finish_assessment(us, reason=UserSurvey.TERMINATION_TIME_EXPIRED)
    us.refresh_from_db()
    assert not _mine(us, qs[1]).on_path
    assert us.score == 10
    assert max_score(us) == 10 + 30
    context = _build_context(us)
    assert (context["max_score"], context["score_pct"]) == (40, 25)


def test_manual_re_evaluation_reads_the_stored_flags(user, survey, qs):
    Survey.objects.filter(pk=survey.pk).update(evaluation_type=Survey.EVALUATION_TYPE_MANUAL_EVALUATION)
    us = _enrol(user, survey)
    for q in qs:
        _pick(us, q)
    _off_path(us, qs[2])
    us.submitted_at = now()
    us.save(update_fields=["submitted_at"])
    assert _evaluate(user, us)["score"] == 60


# ── The setting through the API ──────────────────────────────────────


class _AuthorContext(_Context):
    def __init__(self, user):
        super().__init__(user)
        self.auth_context = AuthContext(
            user_id=UserId(user.id),
            organization_id=OrgId(ORG),
            role_names=frozenset({"org-admin"}),
            perms=frozenset({"surveys:create", "surveys:update"}),
        )


def _mutate(user, name, input_type, values):
    from surveys import schema as schema_module

    result = schema_module.schema.execute_sync(
        f"""mutation M($input: {input_type}!) {{
          {name}(input: $input) {{
            __typename
            ... on SurveyPayload {{ survey {{ id scoreBasis }} }}
            ... on OperationInfo {{ messages {{ field message }} }}
          }}
        }}""",
        variable_values={"input": values},
        context_value=_AuthorContext(user),
    )
    assert result.errors is None, result.errors
    return result.data[name]


def test_create_stores_a_valid_basis_and_refuses_an_invalid_one(user):
    created = _mutate(user, "createSurvey", "SurveyCreateInput", {"surveyType": "survey", "scoreBasis": "answered"})
    assert created["survey"]["scoreBasis"] == "answered"
    assert Survey.objects.get(pk=created["survey"]["id"]).score_basis == "answered"

    before = Survey.objects.count()
    refused = _mutate(user, "createSurvey", "SurveyCreateInput", {"surveyType": "survey", "scoreBasis": "x"})
    assert refused["__typename"] == "OperationInfo"
    assert refused["messages"][0]["field"] == "scoreBasis"
    assert Survey.objects.count() == before


def test_update_stores_a_valid_basis_and_refuses_an_invalid_one(user, survey):
    updated = _mutate(user, "updateSurvey", "SurveyUpdateInput", {"id": survey.id, "scoreBasis": "all"})
    assert updated["survey"]["scoreBasis"] == "all"
    assert Survey.objects.get(pk=survey.pk).score_basis == "all"

    refused = _mutate(user, "updateSurvey", "SurveyUpdateInput", {"id": survey.id, "scoreBasis": "x"})
    assert refused["__typename"] == "OperationInfo"
    assert refused["messages"][0]["field"] == "scoreBasis"
    assert Survey.objects.get(pk=survey.pk).score_basis == "all"


def test_update_refuses_a_null_basis_instead_of_failing_the_write(user, survey):
    refused = _mutate(user, "updateSurvey", "SurveyUpdateInput", {"id": survey.id, "scoreBasis": None})
    assert refused["__typename"] == "OperationInfo"
    assert refused["messages"][0]["field"] == "scoreBasis"
    assert Survey.objects.get(pk=survey.pk).score_basis == "reached"


def test_every_termination_reason_has_a_pdf_label():
    from user_surveys.pdf_service import _TERMINATION_LABELS

    assert set(_TERMINATION_LABELS) == {code for code, _ in UserSurvey.TERMINATION_CHOICES}


# ── What each answer shows ───────────────────────────────────────────


def test_the_pdf_shows_points_only_beside_an_answer_that_counts(user, survey, qs):
    _scored(qs[0], 20)
    us = _enrol(user, survey)
    for q in qs[:2]:
        _pick(us, q)
    _off_path(us, qs[1])
    evaluate_assessment(us)
    us.submitted_at = now()
    us.save(update_fields=["submitted_at"])
    displays = [a["score_display"] for a in _build_context(us)["answers"]]
    # The off-path answer is not listed at all since the 2.9 follow-ups.
    assert displays == ["20/20 Points"]


def test_an_answer_without_a_question_still_scores(user, survey, qs):
    us = _enrol(user, survey)
    orphan = _pick(us, qs[0])
    UserAnswer.objects.filter(pk=orphan.pk).update(question=None)
    evaluate_assessment(us)
    us.refresh_from_db()
    assert us.score == 30


def test_a_stale_off_path_score_is_cleared(user, survey, qs):
    us = _enrol(user, survey)
    stale = _pick(us, qs[1])
    evaluate_assessment(us)
    stale.refresh_from_db()
    assert stale.score == 30
    _off_path(us, qs[1])
    evaluate_assessment(us)
    stale.refresh_from_db()
    us.refresh_from_db()
    assert (stale.score, us.score) == (None, 0)
