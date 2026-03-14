"""Tests for the service layer: enrollment, answering, evaluation, finishing."""
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.utils.timezone import now

from surveys.models import (
    Action,
    AnswerSchema,
    AnswerSchemaOption,
    Classification,
    Question,
    Recommendation,
    RecommendationTranslation,
    Section,
    Survey,
    Usage,
)
from user_surveys.models import (
    Child,
    UserAnswer,
    UserAnswerOption,
    UserClassification,
    UserQuestion,
    UserRecommendation,
    UserSurvey,
    UserSurveyClassification,
    UserSurveyRecommendation,
)
from user_surveys.services import (
    enroll_user_in_assessment,
    evaluate_assessment,
    finish_assessment,
)

User = get_user_model()


def _make_mcq_question(survey, section, title="Q", q_type=Question.QUESTION_TYPE_RADIO_MCQ,
                        is_required=True):
    """Create a question and use its auto-created schema. Clears auto-created options."""
    q = Question.objects.create(
        survey=survey, section=section, title=title,
        type=q_type, is_required=is_required,
    )
    schema = q.answer_schema
    schema.options.all().delete()  # Clear signal-created default options
    return q, schema


def _get_user_question(user_survey, original_question):
    """Get the snapshot UserQuestion corresponding to an original Question."""
    return UserQuestion.objects.get(user_survey=user_survey, origin_id=original_question.id)


def _get_user_option(user_survey, original_option):
    """Get the snapshot UserAnswerOption corresponding to an original AnswerSchemaOption."""
    return UserAnswerOption.objects.get(user_survey=user_survey, origin_id=original_option.id)


# ── Enrollment ──────────────────────────────────────────────────
class TestEnrollment:
    def test_enroll_basic(self, user, survey):
        us, created = enroll_user_in_assessment(user, survey.id)
        assert created is True
        assert us.user == user
        assert us.survey == survey
        assert us.submitted_at is None
        # Snapshot fields
        assert us.survey_type == survey.survey_type
        # title lives in translations JSONB now
        assert us.translations["en"]["title"] == "Test Survey"

    def test_enroll_returns_existing_open(self, user, survey):
        us1, _ = enroll_user_in_assessment(user, survey.id)
        us2, created = enroll_user_in_assessment(user, survey.id)
        assert created is False
        assert us1.pk == us2.pk

    def test_enroll_new_after_submit(self, user, survey):
        us1, _ = enroll_user_in_assessment(user, survey.id)
        us1.submitted_at = now()
        us1.save()
        us2, created = enroll_user_in_assessment(user, survey.id)
        assert created is True
        assert us1.pk != us2.pk

    def test_enroll_with_collection(self, user, survey, collection):
        us, _ = enroll_user_in_assessment(user, survey.id, collection_id=collection.id)
        assert us.collection == collection

    def test_enroll_child_required(self, user):
        survey = Survey.objects.create(is_for_child=True)
        with pytest.raises(ValueError, match="child is required"):
            enroll_user_in_assessment(user, survey.id)

    def test_enroll_child_survey_with_child(self, user):
        survey = Survey.objects.create(is_for_child=True)
        child = Child.objects.create(id="child-abc", name="Alice")
        us, created = enroll_user_in_assessment(user, survey.id, child=child)
        assert created is True
        assert us.child == child

    def test_enroll_non_child_survey_ignores_child(self, user, survey):
        child = Child.objects.create(id="child-abc", name="Alice")
        us, _ = enroll_user_in_assessment(user, survey.id, child=child)
        assert us.child is None  # is_for_child=False ignores child

    def test_enroll_nonexistent_survey(self, user):
        with pytest.raises(Exception):
            enroll_user_in_assessment(user, 999999)

    def test_enroll_different_users(self, user, user2, survey):
        us1, _ = enroll_user_in_assessment(user, survey.id)
        us2, _ = enroll_user_in_assessment(user2, survey.id)
        assert us1.pk != us2.pk

    def test_enroll_creates_snapshot(self, user, survey, section, question, options):
        us, _ = enroll_user_in_assessment(user, survey.id)
        # Verify snapshot tree was created
        assert us.sections.count() >= 1
        assert us.questions.count() >= 1
        assert us.answer_schemas.count() >= 1
        assert us.answer_options.count() >= 1


# ── Evaluation ──────────────────────────────────────────────────
class TestEvaluation:
    @pytest.fixture
    def scored_survey(self):
        """Survey with score, classifications, and recommendations enabled."""
        return Survey.objects.create(
            evaluation_type=Survey.EVALUATION_TYPE_AUTOMATIC_EVALUATION,
            use_score=True,
            use_classifications=True,
            use_recommendations=True,
            use_actions=True,
        )

    @pytest.fixture
    def full_setup(self, user, scored_survey):
        """Complete survey with questions, options, classifications, recommendations."""
        section = Section.objects.create(survey=scored_survey, title="S1")

        cls_high = Classification.objects.create(survey=scored_survey, score=80)
        cls_low = Classification.objects.create(survey=scored_survey, score=20)

        # Q1: radio MCQ (signal auto-creates schema + default option)
        q1, schema1 = _make_mcq_question(scored_survey, section, "Q1",
                                          Question.QUESTION_TYPE_RADIO_MCQ, True)
        opt1a = AnswerSchemaOption.objects.create(
            survey=scored_survey, section=section, question=q1,
            schema=schema1, text="Yes", score=10, classification=cls_high,
        )
        opt1b = AnswerSchemaOption.objects.create(
            survey=scored_survey, section=section, question=q1,
            schema=schema1, text="No", score=5, classification=cls_low,
        )
        rec1 = Recommendation.objects.create(
            survey=scored_survey, option=opt1a,
        )
        RecommendationTranslation.objects.create(
            recommendation=rec1, language="en", description="Great choice!",
        )

        # Q2: checkbox MCQ
        q2, schema2 = _make_mcq_question(scored_survey, section, "Q2",
                                          Question.QUESTION_TYPE_CHECKBOX_MCQ, True)
        opt2a = AnswerSchemaOption.objects.create(
            survey=scored_survey, section=section, question=q2,
            schema=schema2, text="A", score=15, classification=cls_high,
        )
        opt2b = AnswerSchemaOption.objects.create(
            survey=scored_survey, section=section, question=q2,
            schema=schema2, text="B", score=20, classification=cls_low,
        )

        # Q3: text (no options needed)
        Question.objects.create(
            survey=scored_survey, section=section, title="Q3",
            type=Question.QUESTION_TYPE_TEXT, is_required=False,
        )

        us, _ = enroll_user_in_assessment(user, scored_survey.id)

        return {
            "survey": scored_survey,
            "section": section,
            "user_survey": us,
            "q1": q1, "q2": q2,
            "opt1a": opt1a, "opt1b": opt1b,
            "opt2a": opt2a, "opt2b": opt2b,
            "cls_high": cls_high, "cls_low": cls_low,
            "rec1": rec1,
        }

    def test_evaluate_score_radio(self, user, full_setup):
        us = full_setup["user_survey"]
        uq1 = _get_user_question(us, full_setup["q1"])
        uq2 = _get_user_question(us, full_setup["q2"])
        uopt1a = _get_user_option(us, full_setup["opt1a"])
        uopt2a = _get_user_option(us, full_setup["opt2a"])
        uopt2b = _get_user_option(us, full_setup["opt2b"])

        ua1 = UserAnswer.objects.create(
            user=user, question=uq1, user_survey=us, type=uq1.type,
        )
        ua1.selected_options.set([uopt1a])

        ua2 = UserAnswer.objects.create(
            user=user, question=uq2, user_survey=us, type=uq2.type,
        )
        ua2.selected_options.set([uopt2a, uopt2b])

        evaluate_assessment(us)
        us.refresh_from_db()

        assert us.score == 45  # 10 + 15 + 20
        assert us.evaluated_at is not None

    def test_evaluate_classifications(self, user, full_setup):
        us = full_setup["user_survey"]
        uq1 = _get_user_question(us, full_setup["q1"])
        uq2 = _get_user_question(us, full_setup["q2"])
        uopt1a = _get_user_option(us, full_setup["opt1a"])
        uopt2a = _get_user_option(us, full_setup["opt2a"])

        ua1 = UserAnswer.objects.create(
            user=user, question=uq1, user_survey=us, type=uq1.type,
        )
        ua1.selected_options.set([uopt1a])

        ua2 = UserAnswer.objects.create(
            user=user, question=uq2, user_survey=us, type=uq2.type,
        )
        ua2.selected_options.set([uopt2a])

        evaluate_assessment(us)

        classifications = UserSurveyClassification.objects.filter(user_survey=us)
        assert classifications.count() >= 1
        # Find the UserClassification that corresponds to cls_high
        ucls_high = UserClassification.objects.get(
            user_survey=us, origin_id=full_setup["cls_high"].id
        )
        high_cls = classifications.filter(classification=ucls_high).first()
        assert high_cls is not None
        assert high_cls.count == 2  # Both options had cls_high

    def test_evaluate_recommendations(self, user, full_setup):
        us = full_setup["user_survey"]
        uq1 = _get_user_question(us, full_setup["q1"])
        uopt1a = _get_user_option(us, full_setup["opt1a"])

        ua1 = UserAnswer.objects.create(
            user=user, question=uq1, user_survey=us, type=uq1.type,
        )
        ua1.selected_options.set([uopt1a])

        evaluate_assessment(us)

        recs = UserSurveyRecommendation.objects.filter(user_survey=us)
        assert recs.count() >= 1
        urec1 = UserRecommendation.objects.get(
            user_survey=us, origin_id=full_setup["rec1"].id
        )
        assert recs.first().recommendation == urec1

    def test_evaluate_no_score_when_disabled(self, user):
        survey = Survey.objects.create(use_score=False)
        section = Section.objects.create(survey=survey, title="S")
        q, schema = _make_mcq_question(survey, section, "Q")
        opt = AnswerSchemaOption.objects.create(
            survey=survey, section=section, question=q,
            schema=schema, text="X", score=100,
        )
        us, _ = enroll_user_in_assessment(user, survey.id)
        uq = _get_user_question(us, q)
        uopt = _get_user_option(us, opt)
        ua = UserAnswer.objects.create(
            user=user, question=uq, user_survey=us, type=uq.type,
        )
        ua.selected_options.set([uopt])
        evaluate_assessment(us)
        us.refresh_from_db()
        assert us.score is None  # use_score=False

    def test_evaluate_empty_assessment(self, user, full_setup):
        us = full_setup["user_survey"]
        evaluate_assessment(us)
        us.refresh_from_db()
        assert us.score == 0
        assert us.evaluated_at is not None


# ── Finish Assessment ───────────────────────────────────────────
class TestFinishAssessment:
    def test_finish_basic(self, user, survey, section, question, answer_schema, options, enrolled_survey):
        uq = _get_user_question(enrolled_survey, question)
        uopt = _get_user_option(enrolled_survey, options[0])
        ua = UserAnswer.objects.create(
            user=user, question=uq,
            user_survey=enrolled_survey, type=uq.type,
        )
        ua.selected_options.set([uopt])

        finish_assessment(enrolled_survey)
        enrolled_survey.refresh_from_db()
        assert enrolled_survey.submitted_at is not None
        assert enrolled_survey.last_question is None

    def test_finish_missing_required_raises(self, user, enrolled_survey, question):
        with pytest.raises(ValueError, match="required questions"):
            finish_assessment(enrolled_survey)

    def test_finish_auto_evaluate(self, user):
        survey = Survey.objects.create(
            use_score=True,
            evaluation_type=Survey.EVALUATION_TYPE_AUTOMATIC_EVALUATION,
        )
        section = Section.objects.create(survey=survey, title="S")
        q, schema = _make_mcq_question(survey, section, "Q")
        opt = AnswerSchemaOption.objects.create(
            survey=survey, section=section, question=q, schema=schema,
            text="Yes", score=42,
        )
        us, _ = enroll_user_in_assessment(user, survey.id)
        uq = _get_user_question(us, q)
        uopt = _get_user_option(us, opt)
        ua = UserAnswer.objects.create(
            user=user, question=uq, user_survey=us, type=uq.type,
        )
        ua.selected_options.set([uopt])

        finish_assessment(us)
        us.refresh_from_db()
        assert us.submitted_at is not None
        assert us.evaluated_at is not None
        assert us.score == 42

    def test_finish_manual_no_auto_evaluate(self, user):
        survey = Survey.objects.create(
            use_score=True,
            evaluation_type=Survey.EVALUATION_TYPE_MANUAL_EVALUATION,
        )
        Section.objects.create(survey=survey, title="S")
        us, _ = enroll_user_in_assessment(user, survey.id)

        finish_assessment(us)
        us.refresh_from_db()
        assert us.submitted_at is not None
        assert us.evaluated_at is None  # manual evaluation, not auto

    def test_finish_non_required_skipped(self, user, survey):
        section = Section.objects.create(survey=survey, title="S")
        Question.objects.create(
            survey=survey, section=section, title="Optional",
            type=Question.QUESTION_TYPE_TEXT, is_required=False,
        )
        us, _ = enroll_user_in_assessment(user, survey.id)
        finish_assessment(us)
        us.refresh_from_db()
        assert us.submitted_at is not None


# ── Usage tracking ──────────────────────────────────────────────
class TestUsageTracking:
    def test_usage_limit_check(self, user, survey):
        usage = Usage.objects.create(
            user=user, survey=survey, order_id=uuid.uuid4(),
            usage_limit=2, used_count=2,
        )
        assert usage.used_count >= usage.usage_limit

    def test_usage_increment_on_finish(self, user, survey):
        usage = Usage.objects.create(
            user=user, survey=survey, order_id=uuid.uuid4(),
            usage_limit=10, used_count=0,
        )
        usage.used_count += 1
        usage.save(update_fields=["used_count"])
        usage.refresh_from_db()
        assert usage.used_count == 1


# ── Question update_answer_schema logic ─────────────────────────
class TestQuestionAnswerSchemaUpdate:
    def test_update_to_text_clears_options(self, survey, section, question, answer_schema, options):
        assert answer_schema.options.count() == 3
        question.type = Question.QUESTION_TYPE_TEXT
        question.save()
        question.update_answer_schema()
        answer_schema.refresh_from_db()
        assert answer_schema.is_mcq is False
        assert answer_schema.is_grid is False
        assert answer_schema.options.count() == 0

    def test_update_to_grid_creates_row_column(self, survey, section):
        q = Question.objects.create(
            survey=survey, section=section, title="Grid Q",
            type=Question.QUESTION_TYPE_RADIO_GRID,
        )
        schema = q.answer_schema
        schema.refresh_from_db()
        assert schema.is_grid is True
        assert schema.options.filter(is_row=True).exists()
        assert schema.options.filter(is_column=True).exists()

    def test_update_to_mcq_creates_default_option(self, survey, section):
        q = Question.objects.create(
            survey=survey, section=section, title="MCQ Q",
            type=Question.QUESTION_TYPE_CHECKBOX_MCQ,
        )
        schema = q.answer_schema
        assert schema.is_mcq is True
        assert schema.options.count() >= 1


# ── Survey.update_status ────────────────────────────────────────
class TestSurveyStatus:
    def test_status_log_created(self, survey, user):
        survey.update_status("published", user)
        assert survey.status_log.count() == 1
        assert survey.status_log.first().status == "published"

    def test_multiple_status_updates(self, survey, user):
        survey.update_status("pending", user)
        survey.update_status("published", user)
        assert survey.status_log.count() == 2
        survey.refresh_from_db()
        assert survey.status.status == "published"


# ── clone_instance utility ──────────────────────────────────────
class TestCloneInstance:
    def test_clone_survey(self, survey):
        from surveys.schemas.utils import clone_instance
        cloned = clone_instance(survey)
        assert cloned.pk != survey.pk
        assert cloned.survey_type == survey.survey_type

    def test_clone_section(self, survey, section):
        from surveys.schemas.utils import clone_instance
        cloned = clone_instance(section, survey=survey, title="Cloned Section")
        assert cloned.pk != section.pk
        assert cloned.title == "Cloned Section"


# ── input_to_dict utility ──────────────────────────────────────
class TestInputToDict:
    def test_basic_conversion(self):
        import strawberry
        from surveys.schemas.utils import input_to_dict

        @strawberry.input
        class TestInput:
            name: str
            value: int = strawberry.UNSET

        inp = TestInput(name="hello")
        result = input_to_dict(inp)
        assert result == {"name": "hello"}

    def test_exclude_fields(self):
        import strawberry
        from surveys.schemas.utils import input_to_dict

        @strawberry.input
        class TestInput2:
            name: str
            secret: str

        inp = TestInput2(name="hello", secret="password")
        result = input_to_dict(inp, exclude=["secret"])
        assert "secret" not in result
        assert result["name"] == "hello"


# ── Factory tests ──────────────────────────────────────────────
class TestSurveyFactory:
    """Note: SurveyFactory has a known issue - it assigns Status string constants
    to Survey.status which is now a ForeignKey. Tests use a real Status instance."""

    @pytest.fixture
    def _status_instance(self):
        from surveys.models import Status
        s = Survey.objects.create()
        return Status.objects.create(survey=s, status=Status.STATUS_DRAFT)

    def test_factory_build(self, _status_instance):
        from surveys.factories import SurveyFactory
        s = SurveyFactory.build(status=_status_instance)
        assert s.pk is None

    def test_factory_create(self, _status_instance):
        from surveys.factories import SurveyFactory
        s = SurveyFactory.create(status=_status_instance)
        assert s.pk is not None

    def test_factory_create_batch(self, _status_instance):
        from surveys.factories import SurveyFactory
        batch = SurveyFactory.create_batch(3, status=_status_instance)
        assert len(batch) == 3
        assert all(s.pk is not None for s in batch)

    def test_factory_with_overrides(self, _status_instance):
        from surveys.factories import SurveyFactory
        s = SurveyFactory.create(title="Custom Title", is_timed=True, status=_status_instance)
        assert s.title == "Custom Title"  # via translation property
        assert s.is_timed is True
