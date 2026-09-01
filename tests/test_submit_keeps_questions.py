"""Regression coverage for submitting an attempt destroying its own snapshot.

`finish_assessment` used to delete every `UserQuestion` without an answer. The
`UserSection` rows survived, so `userSurvey.sections` still returned them with
`questions: []` — mobile derives its denominator by walking those, which is why
a partial submission rendered `answered 0/0` with an empty answer review. The
deletion was also unrecoverable: the snapshot is the only record of what this
user was actually asked.

These tests drive the real mutations end to end. The older coverage in
`test_usage_and_results` sets `submitted_at` directly, which is exactly why it
did not catch this.
"""

import pytest

from surveys.models import AnswerSchemaOption, Question, Section
from user_surveys.models import UserAnswer, UserQuestion
from user_surveys.services import enroll_user_in_assessment


ANSWER = """
mutation Answer($us: Int!, $q: Int!, $a: [String!]!) {
  answerQuestion(userSurveyId: $us, questionId: $q, answer: $a) {
    __typename
    ... on UserAnswerType { id }
    ... on OperationInfo { messages { message } }
  }
}
"""

FINISH = """
mutation Finish($us: Int!) { finishAssessment(userSurveyId: $us) { status score } }
"""

RESULTS = """
query Results($input: UserSurveysListInput!) {
  userSurvey(userSurveysListInput: $input) {
    items {
      id
      questions { id }
      sections { id questions { id answers { id answer } } }
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
    def __init__(self, user):
        self.request = None
        self.identity = _Identity(user)
        self.auth_context = None
        self.currency = None


def _run(user, document, **variables):
    from surveys import schema as schema_module

    result = schema_module.schema.execute_sync(
        document, variable_values=variables or None, context_value=_Context(user)
    )
    assert result.errors is None, result.errors
    return result.data


def _build_survey(survey, sections=2, per_section=2):
    """Two sections of two MCQ questions each, so a partial submission can leave
    one section entirely unanswered."""
    for si in range(sections):
        section = Section.objects.create(survey=survey, title=f"Section {si}", description="")
        questions = list(section.questions.all())  # a signal seeds one
        while len(questions) < per_section:
            questions.append(
                Question.objects.create(survey=survey, section=section, title="")
            )
        for qi, question in enumerate(questions):
            question.title = f"Q{si}-{qi}"
            question.type = Question.QUESTION_TYPE_RADIO_MCQ
            question.is_required = False
            question.save()
            question.answer_schema.options.all().delete()
            for score in (10, 20):
                AnswerSchemaOption.objects.create(
                    survey=survey, section=section, question=question,
                    schema=question.answer_schema, text=f"opt{score}", score=score,
                )


def _answer(user, user_survey, user_question):
    option = user_question.answer_schema.options.first()
    _run(user, ANSWER, us=user_survey.id, q=user_question.id, a=[str(option.id)])


def _results(user, user_survey):
    data = _run(
        user, RESULTS,
        input={"limit": 1, "offset": 0, "filters": {"id": user_survey.id}, "sort": None},
    )
    return data["userSurvey"]["items"][0]


def _snapshot_questions(user_survey):
    return list(UserQuestion.objects.filter(user_survey=user_survey).order_by("id"))


def test_a_fully_answered_attempt_keeps_every_question_and_answer(user, survey):
    _build_survey(survey)
    user_survey, _ = enroll_user_in_assessment(user, survey.id)
    questions = _snapshot_questions(user_survey)
    assert len(questions) == 4

    for question in questions:
        _answer(user, user_survey, question)
    _run(user, FINISH, us=user_survey.id)

    payload = _results(user, user_survey)
    assert len(payload["questions"]) == 4
    assert [len(s["questions"]) for s in payload["sections"]] == [2, 2]
    answers = [q["answers"] for s in payload["sections"] for q in s["questions"]]
    assert all(a for a in answers), "every question comes back with its answer"


def test_a_skipped_question_survives_submission_and_simply_has_no_answer(user, survey):
    """The defect. Answering only the first section used to delete the other
    three questions outright, leaving section two with `questions: []` — a zero
    denominator on the results screen and an empty answer review."""
    _build_survey(survey)
    user_survey, _ = enroll_user_in_assessment(user, survey.id)
    questions = _snapshot_questions(user_survey)

    _answer(user, user_survey, questions[0])
    _run(user, FINISH, us=user_survey.id)

    payload = _results(user, user_survey)
    assert len(payload["questions"]) == 4, "the snapshot is intact"
    assert [len(s["questions"]) for s in payload["sections"]] == [2, 2], (
        "the fully-skipped section still carries its questions"
    )

    answered = [q for s in payload["sections"] for q in s["questions"] if q["answers"]]
    unanswered = [q for s in payload["sections"] for q in s["questions"] if not q["answers"]]
    assert len(answered) == 1
    assert len(unanswered) == 3, "skipped questions render as unanswered, not as absent"


def test_submitting_leaves_every_answer_linked_to_its_question(user, survey):
    """`UserAnswer.question` is SET_NULL, so deleting snapshot questions used to
    orphan answers as well — and `evaluate_assessment` skips orphaned answers,
    so scoring silently lost them too."""
    _build_survey(survey)
    user_survey, _ = enroll_user_in_assessment(user, survey.id)
    questions = _snapshot_questions(user_survey)
    for question in questions[:2]:
        _answer(user, user_survey, question)

    _run(user, FINISH, us=user_survey.id)

    assert UserAnswer.objects.filter(user_survey=user_survey).count() == 2
    assert UserAnswer.objects.filter(user_survey=user_survey, question__isnull=True).count() == 0
