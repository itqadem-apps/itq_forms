"""Story survey-flow 1.3 — sections become optional.

A question with no section is authored, enforced, scored, shuffled and counted like any other
(`forms:AD-9`, `forms:AD-13`): no required, score or progress query filters on section membership.
Its answer schema and options carry a null section, and removing a section can no longer cascade
them away.
"""

import random
import uuid

import pytest

from surveys.inputs import QuestionInput, QuestionPlacementInput
from surveys.models import AnswerSchema, AnswerSchemaOption, Question, Section, Survey
from surveys.question_order import renumber_questions
from surveys.schemas.mutations.questions import QuestionMutations
from user_surveys.models import UserAnswer, UserQuestion, UserSurvey
from user_surveys.services import enroll_user_in_assessment, evaluate_assessment, finish_assessment
from user_surveys.types import user_survey as user_survey_types
from user_surveys.types.user_survey import UserSurveyType

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")


def _resolver(cls, name):
    fn = getattr(cls, name)
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def _create(**kw):
    kw.setdefault("input", QuestionInput(title="loose", type="text"))
    return _resolver(QuestionMutations, "create_question")(QuestionMutations(), None, django_user=None, **kw)


def _sectionless(survey, title="loose", q_type=Question.QUESTION_TYPE_TEXT, is_required=False):
    q = _create(survey_id=str(survey.id), input=QuestionInput(title=title, type=q_type, is_required=is_required))
    return Question.objects.get(pk=q.pk)


def _orders(survey):
    return list(Question.objects.filter(survey=survey).order_by("order").values_list("id", flat=True))


@pytest.fixture
def two_sections(survey):
    a = Section.objects.create(survey=survey, title="A")
    b = Section.objects.create(survey=survey, title="B")
    return a, b


# ── Authoring ───────────────────────────────────────────────────


def test_create_question_with_only_a_survey_makes_a_sectionless_question_at_the_end(survey, two_sections):
    q = _sectionless(survey)

    assert q.section_id is None and q.survey_id == survey.id
    assert _orders(survey)[-1] == q.id
    schema = AnswerSchema.objects.get(question=q)
    assert schema.section_id is None
    assert not AnswerSchemaOption.objects.filter(question=q, section__isnull=False).exists()


def test_create_question_needs_a_section_or_a_survey(survey):
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError) as excinfo:
        _create()
    assert set(excinfo.value.message_dict) == {"section_id"}


def test_create_question_refuses_a_section_from_another_survey(survey, two_sections):
    from django.core.exceptions import ValidationError

    other = Survey.objects.create(organization_id=ORG)
    with pytest.raises(ValidationError) as excinfo:
        _create(section_id=str(two_sections[0].id), survey_id=str(other.id))
    assert set(excinfo.value.message_dict) == {"survey_id"}


# ── The cascade ─────────────────────────────────────────────────


def test_removing_a_section_cannot_take_the_schema_of_a_question_that_left_it(survey, two_sections):
    a, b = two_sections
    (q,) = b.questions.all()
    schema = q.answer_schema
    # A question already out of B whose schema and options still name it (a pre-1.3 row shape).
    Question.objects.filter(pk=q.pk).update(section=None)

    b.delete()

    schema.refresh_from_db()
    assert schema.section_id is None
    assert AnswerSchemaOption.objects.filter(schema=schema).exists()
    assert not AnswerSchemaOption.objects.filter(schema=schema, section__isnull=False).exists()


def test_moving_a_question_out_of_its_section_repoints_its_schema_and_options(survey, two_sections):
    a, b = two_sections
    (a1,) = a.questions.values_list("id", flat=True)
    (b1,) = b.questions.values_list("id", flat=True)

    _resolver(QuestionMutations, "reorder_survey_questions")(
        QuestionMutations(),
        None,
        survey_id=str(survey.id),
        placements=[
            QuestionPlacementInput(question_id=str(a1), section_id=str(a.id)),
            QuestionPlacementInput(question_id=str(b1), section_id=None),
        ],
        django_user=None,
    )

    assert Question.objects.get(pk=b1).section_id is None
    assert AnswerSchema.objects.get(question_id=b1).section_id is None
    assert not AnswerSchemaOption.objects.filter(question_id=b1, section__isnull=False).exists()


# ── Order (`forms:AD-4`) ────────────────────────────────────────


def test_a_sectionless_question_between_sections_stays_there_on_renumber(survey, two_sections):
    a, b = two_sections
    loose = _sectionless(survey)
    a_ids = list(a.questions.values_list("id", flat=True))
    b_ids = list(b.questions.values_list("id", flat=True))
    # Place it between A and B.
    for i, pk in enumerate(a_ids + [loose.id] + b_ids, start=1):
        Question.objects.filter(pk=pk).update(order=i)

    renumber_questions(survey.id)
    assert _orders(survey) == a_ids + [loose.id] + b_ids

    # A new question in A lands at the end of A, not after the sectionless one.
    added = _create(section_id=str(a.id))
    assert _orders(survey) == a_ids + [added.pk, loose.id] + b_ids


# ── Required check, score, shuffle ─────────────────────────────


def test_finish_enforces_a_required_sectionless_question(user, survey, two_sections):
    _sectionless(survey, is_required=True)
    Question.objects.filter(survey=survey, section__isnull=False).update(is_required=False)
    us, _ = enroll_user_in_assessment(user, survey.id)

    with pytest.raises(ValueError, match="required"):
        finish_assessment(us)


def test_a_forced_termination_still_skips_the_required_check(user, survey, two_sections):
    _sectionless(survey, is_required=True)
    us, _ = enroll_user_in_assessment(user, survey.id)

    finish_assessment(us, reason=UserSurvey.TERMINATION_TIME_EXPIRED)

    us.refresh_from_db()
    assert us.submitted_at is not None
    assert us.termination_reason == UserSurvey.TERMINATION_TIME_EXPIRED


def test_evaluate_scores_a_sectionless_answer(user):
    survey = Survey.objects.create(
        organization_id=ORG,
        evaluation_type=Survey.EVALUATION_TYPE_AUTOMATIC_EVALUATION,
        use_score=True,
    )
    q = _sectionless(survey, q_type=Question.QUESTION_TYPE_RADIO_MCQ)
    schema = q.answer_schema
    schema.options.all().delete()
    opt = AnswerSchemaOption.objects.create(survey=survey, question=q, schema=schema, text="Yes", score=7)
    us, _ = enroll_user_in_assessment(user, survey.id)
    uq = UserQuestion.objects.get(user_survey=us, origin_id=q.id)
    assert uq.section_id is None
    ua = UserAnswer.objects.create(user=user, question=uq, user_survey=us, type=uq.type)
    ua.selected_options.set(us.answer_options.filter(origin_id=opt.id))

    evaluate_assessment(us)

    us.refresh_from_db()
    assert us.score == 7


def test_randomize_shuffles_sectionless_questions_too(user, survey, two_sections, monkeypatch):
    loose = _sectionless(survey)
    Survey.objects.filter(pk=survey.pk).update(randomize_questions=True)
    shuffled = []
    monkeypatch.setattr(random, "shuffle", lambda seq: (shuffled.extend(seq), seq.reverse()))

    us, _ = enroll_user_in_assessment(user, survey.id)

    origins = {uq.origin_id for uq in shuffled}
    assert loose.id in origins
    assert origins == set(Question.objects.filter(survey=survey).values_list("id", flat=True))


# ── Progress ────────────────────────────────────────────────────


def test_progress_counts_sectionless_questions_and_never_exceeds_100(user, survey, two_sections, monkeypatch):
    _sectionless(survey)
    us, _ = enroll_user_in_assessment(user, survey.id)
    monkeypatch.setattr(user_survey_types, "get_django_user", lambda info: user)
    progress = UserSurveyType.progress

    for uq in UserQuestion.objects.filter(user_survey=us, section__isnull=False):
        UserAnswer.objects.create(user=user, question=uq, user_survey=us, type=uq.type, answer="x")
    assert progress(us, None) == 66  # 2 of 3, the sectionless one still open

    uq = UserQuestion.objects.get(user_survey=us, section__isnull=True)
    UserAnswer.objects.create(user=user, question=uq, user_survey=us, type=uq.type, answer="x")
    assert progress(us, None) == 100
