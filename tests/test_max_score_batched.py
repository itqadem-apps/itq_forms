"""`maxScore` costs a fixed number of queries per list, not per attempt (`forms:AD-10`,
`forms:AD-17`)."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils.timezone import now

from surveys.models import AnswerSchemaOption, Question, ScoreBasis, Survey
from surveys.question_order import renumber_questions
from user_surveys.models import UserAnswer, UserAnswerOption, UserQuestion, UserSurvey
from user_surveys.services import enroll_user_in_assessment, max_score, max_scores
from user_surveys.types import max_score_priming
from user_surveys.types.user_survey import UserSurveyType

# `answered` first, so any two consecutive attempts include the basis that runs the extra query.
BASES = [ScoreBasis.ANSWERED, ScoreBasis.REACHED, ScoreBasis.ALL]

LIST_QUERY = """query L($input: UserSurveysListInput!) {
  userSurvey(userSurveysListInput: $input) { total items { id %s } }
}"""

NESTED_QUERY = """query S($id: ID!) { survey(id: $id) { userSurveys { id %s } } }"""


class _Identity:
    def __init__(self, user):
        self.subject_str = user.id
        self.email_str = user.email
        self.preferred_username = user.username
        self.first_name = ""
        self.last_name = ""


class _Context:
    def __init__(self, user):
        self.request = None
        self.identity = _Identity(user)
        self.auth_context = None
        self.currency = None


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


def _pick(us, question):
    uq = _mine(us, question)
    answer = UserAnswer.objects.create(user=us.user, question=uq, user_survey=us, type=uq.type)
    chosen = question.answer_schema.options.first()
    answer.selected_options.set([UserAnswerOption.objects.get(user_survey=us, origin_id=chosen.id)])
    return answer


def _off_path(us, question):
    UserQuestion.objects.filter(pk=_mine(us, question).pk).update(on_path=False)


def _spy(monkeypatch):
    """Record the attempts each batch computes."""
    calls = []
    real = max_score_priming.max_scores
    monkeypatch.setattr(
        max_score_priming, "max_scores", lambda items: calls.append([us.id for us in items]) or real(items)
    )
    return calls


def _execute(user, query, variables):
    from surveys import schema as schema_module

    result = schema_module.schema.execute_sync(query, variable_values=variables, context_value=_Context(user))
    assert result.errors is None, result.errors
    return result.data


def _list(user, fields="maxScore"):
    variables = {"input": {"limit": 100, "offset": 0, "filters": {}, "sort": None}}
    with CaptureQueriesContext(connection) as captured:
        data = _execute(user, LIST_QUERY % fields, variables)
    return {int(i["id"]): i.get("maxScore") for i in data["userSurvey"]["items"]}, len(captured.captured_queries)


def _attempts(user, survey, qs, n):
    """`n` attempts across the three bases, with skipped and unanswered questions."""
    made = []
    for i in range(n):
        us = _enrol(user, survey, BASES[i % 3])
        _pick(us, qs[0])
        if i % 2:
            _pick(us, qs[2])
        UserAnswer.objects.create(user=user, question=_mine(us, qs[1]), user_survey=us, type="radio")
        _off_path(us, qs[(i + 1) % 3])
        # Submitted, so the next enrolment opens a new attempt instead of returning this one.
        UserSurvey.objects.filter(pk=us.pk).update(submitted_at=now())
        made.append(UserSurvey.objects.get(pk=us.pk))
    return made


@pytest.fixture
def mixed(survey, qs):
    """Distinct per-question maxima, so a wrongly counted question changes the total."""
    _scored(qs[0], 5, 20, -3)
    qs[1].type = Question.QUESTION_TYPE_CHECKBOX_MCQ
    qs[1].save(update_fields=["type"])
    _scored(qs[1], 5, 20, -3)
    _scored(qs[2], 7)
    return qs


def test_parity_with_max_score_under_every_basis(user, survey, mixed):
    attempts = _attempts(user, survey, mixed, 6)
    # Per-question maxima 20 / 25 / 7. answered: q1 (+q3 when picked); reached: on-path q1+q2;
    # all: every question.
    expected = dict(zip((us.id for us in attempts), (20, 45, 52, 27, 45, 52)))
    assert max_scores(attempts) == expected
    assert {us.id: max_score(us) for us in attempts} == expected
    assert _list(user)[0] == expected


def test_query_count_does_not_grow_with_attempts(user, survey, mixed):
    two_attempts = _attempts(user, survey, mixed, 2)
    assert two_attempts[0].score_basis == ScoreBasis.ANSWERED, "the baseline must run every batched query"
    _, two = _list(user)
    _attempts(user, survey, mixed, 4)
    values, six = _list(user)
    assert len(values) == 6
    assert two == six


def test_a_list_without_max_score_runs_no_extra_query(user, survey, mixed, monkeypatch):
    _attempts(user, survey, mixed, 3)
    _, primed = _list(user, fields="score")
    from user_surveys.schemas.queries import user_surveys as list_module

    monkeypatch.setattr(list_module, "prime_max_scores", lambda *a: None)
    _, baseline = _list(user, fields="score")
    assert primed == baseline


def test_max_score_inside_a_fragment_is_primed(user, survey, mixed, monkeypatch):
    attempts = _attempts(user, survey, mixed, 2)
    calls = _spy(monkeypatch)
    variables = {"input": {"limit": 100, "offset": 0, "filters": {}, "sort": None}}
    _execute(
        user,
        """query L($input: UserSurveysListInput!) {
          userSurvey(userSurveysListInput: $input) { items { ...M } }
        }
        fragment M on UserSurveyType { maxScore }""",
        variables,
    )
    assert [sorted(c) for c in calls] == [sorted(us.id for us in attempts)]


def test_scoring_off_is_null_and_not_computed(user, survey, mixed, monkeypatch):
    scored, unscored = _attempts(user, survey, mixed, 2)
    UserSurvey.objects.filter(pk=unscored.pk).update(use_score=False)
    calls = _spy(monkeypatch)
    values, _ = _list(user)
    assert values == {scored.id: max_score(scored), unscored.id: None}
    assert calls == [[scored.id]]


def test_the_nested_list_is_primed(user, survey, mixed, monkeypatch):
    Survey.objects.filter(pk=survey.pk).update(status="published")
    first = _enrol(user, survey, ScoreBasis.ANSWERED)
    _pick(first, mixed[0])
    # `userSurveys` lists open attempts only, and enrolment returns an open one instead of making
    # a second; submitting `first` lets `second` be created, then reopening it lists both.
    UserSurvey.objects.filter(pk=first.pk).update(submitted_at=now())
    second = _enrol(user, survey, ScoreBasis.REACHED)
    _off_path(second, mixed[2])
    UserSurvey.objects.filter(pk=first.pk).update(submitted_at=None)
    calls = _spy(monkeypatch)
    data = _execute(user, NESTED_QUERY % "maxScore", {"id": survey.id})
    values = {int(i["id"]): i["maxScore"] for i in data["survey"]["userSurveys"]}
    assert values == {us.id: max_score(UserSurvey.objects.get(pk=us.pk)) for us in (first, second)}
    assert [sorted(c) for c in calls] == [sorted((first.id, second.id))]


def test_an_empty_list_costs_nothing_extra(user, monkeypatch):
    values, primed = _list(user)
    from user_surveys.schemas.queries import user_surveys as list_module

    monkeypatch.setattr(list_module, "prime_max_scores", lambda *a: None)
    _, baseline = _list(user)
    assert values == {}
    assert primed == baseline
    assert max_scores([]) == {}


def test_the_single_attempt_results_query_is_unchanged(user, survey, qs):
    us = _enrol(user, survey)
    _pick(us, qs[0])
    variables = {"input": {"limit": 1, "offset": 0, "filters": {"id": us.id}, "sort": None}}
    data = _execute(user, LIST_QUERY % "maxScore", variables)
    # Three radios at 30 each, default `reached` basis, no flow so all on the path: 90.
    assert data["userSurvey"]["items"][0]["maxScore"] == max_score(us) == 90


def test_an_unprimed_attempt_falls_back_to_max_score(user, survey, mixed):
    us = _attempts(user, survey, mixed, 2)[1]
    assert "_primed_max_score" not in us.__dict__
    assert UserSurveyType.max_score(us) == max_score(us) == 45
    UserSurvey.objects.filter(pk=us.pk).update(use_score=False)
    assert UserSurveyType.max_score(UserSurvey.objects.get(pk=us.pk)) is None
