"""Tests for all Django models: creation, relationships, constraints."""
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.utils.timezone import now

from surveys.models import (
    Action,
    ActionTranslation,
    AnswerSchema,
    AnswerSchemaOption,
    AnswerSchemaOptionTranslation,
    Classification,
    ClassificationTranslation,
    Price,
    Question,
    QuestionTranslation,
    Recommendation,
    RecommendationTranslation,
    Section,
    SectionTranslation,
    Status,
    Survey,
    SurveyMediaAsset,
    SurveyTranslation,
    Usage,
)
from survey_collections.models import SurveyCollection, SurveyCollectionTranslation
from taxonomy.models import Category, CategoryTranslation
from user_surveys.models import (
    Child,
    UserAnswer,
    UserSurvey,
    UserSurveyClassification,
    UserSurveyRecommendation,
)

User = get_user_model()


# ── User model ──────────────────────────────────────────────────
class TestUserModel:
    def test_create_user(self, user):
        assert user.pk is not None
        assert user.username == "testuser"
        assert str(user) == "testuser"

    def test_user_keycloak_pk(self, user):
        assert user.pk.startswith("keycloak-")

    def test_user_duplicate_pk_raises(self, user):
        with pytest.raises(IntegrityError):
            User.objects.create(id=user.pk, username="dup")


# ── Survey model ────────────────────────────────────────────────
class TestSurveyModel:
    def test_create_survey(self, survey):
        assert survey.pk is not None
        assert survey.title == "Test Survey"
        assert survey.survey_type == Survey.ASSESSMENT_TYPE_SURVEY

    def test_survey_defaults(self):
        s = Survey.objects.create(title="Defaults")
        assert s.display_option == Survey.DISPLAY_OPTION_BY_QUESTION
        assert s.evaluation_type == Survey.EVALUATION_TYPE_AUTOMATIC_EVALUATION
        assert s.use_score is True
        assert s.is_timed is False
        assert s.is_for_child is False

    def test_survey_str(self, survey):
        assert str(survey) == "Test Survey"

    def test_survey_ordering(self):
        s1 = Survey.objects.create(title="First")
        s2 = Survey.objects.create(title="Second")
        surveys = list(Survey.objects.all())
        assert surveys[0].pk == s2.pk  # -created_at ordering

    def test_update_status(self, survey, user):
        status_entry = survey.update_status(Status.STATUS_PUBLISHED, user)
        assert status_entry.status == Status.STATUS_PUBLISHED
        survey.refresh_from_db()
        assert survey.status_id == status_entry.id

    def test_survey_all_types(self):
        for type_val, _ in Survey.ASSESSMENT_TYPES:
            s = Survey.objects.create(title=f"Type {type_val}", survey_type=type_val)
            assert s.survey_type == type_val

    def test_survey_all_display_options(self):
        for opt_val, _ in Survey.DISPLAY_OPTIONS:
            s = Survey.objects.create(title=f"Display {opt_val}", display_option=opt_val)
            assert s.display_option == opt_val

    def test_survey_properties(self, survey):
        assert survey.get_survey_type == "Survey"
        assert survey.get_evaluation_type == "Automatic Evaluation"
        assert survey.get_display_option == "By Question"

    def test_survey_category_fk(self, survey, category):
        survey.category = category
        survey.save()
        survey.refresh_from_db()
        assert survey.category_id == category.pk


# ── Status model ────────────────────────────────────────────────
class TestStatusModel:
    def test_create_status(self, survey):
        status = Status.objects.create(survey=survey, status=Status.STATUS_DRAFT)
        assert status.status == Status.STATUS_DRAFT
        assert status.get_status == "Draft"

    def test_status_all_choices(self, survey):
        for status_val, label in Status.STATUS_CHOICES:
            s = Status.objects.create(survey=survey, status=status_val)
            assert s.get_status == str(label)


# ── Section model ───────────────────────────────────────────────
class TestSectionModel:
    def test_create_section(self, section):
        assert section.pk is not None
        assert section.title == "Section 1"
        assert section.order == 1

    def test_section_auto_order(self, survey):
        s1 = Section.objects.create(survey=survey, title="S1")
        s2 = Section.objects.create(survey=survey, title="S2")
        assert s1.order == 1
        assert s2.order == 2

    def test_section_survey_relationship(self, survey, section):
        assert section.survey_id == survey.pk
        assert section in survey.sections.all()

    def test_section_ordering(self, survey):
        s2 = Section.objects.create(survey=survey, title="B", order=2)
        s1 = Section.objects.create(survey=survey, title="A", order=1)
        sections = list(Section.objects.filter(survey=survey))
        assert sections[0].order <= sections[1].order


# ── Question model ──────────────────────────────────────────────
class TestQuestionModel:
    def test_create_question(self, question):
        assert question.pk is not None
        assert question.is_required is True
        assert question.type == Question.QUESTION_TYPE_RADIO_MCQ

    def test_question_auto_order(self, survey, section):
        # Section signal auto-creates 1 question already (order=1)
        q_new = Question.objects.create(survey=survey, section=section, title="Q_new")
        assert q_new.order == 2

    def test_question_all_types(self, survey, section):
        for type_val, _ in Question.QUESTION_TYPE_CHOICES:
            q = Question.objects.create(
                survey=survey, section=section, title=f"Type {type_val}", type=type_val
            )
            assert q.type == type_val

    def test_question_section_relationship(self, question, section):
        assert question in section.questions.all()

    def test_question_mcq_types_property(self, question):
        assert "radio" in question.mcq_types
        assert "checkbox" in question.mcq_types
        assert "dropdown" in question.mcq_types

    def test_question_grid_types_property(self, question):
        assert "radio_grid" in question.grid_types
        assert "checkbox_grid" in question.grid_types


# ── AnswerSchema model ──────────────────────────────────────────
class TestAnswerSchemaModel:
    def test_create_answer_schema(self, answer_schema):
        assert answer_schema.pk is not None
        assert answer_schema.is_mcq is True
        assert answer_schema.is_grid is False

    def test_answer_schema_one_to_one(self, question, answer_schema):
        assert question.answer_schema == answer_schema

    def test_answer_schema_second_raises(self, survey, section, question, answer_schema):
        with pytest.raises(IntegrityError):
            AnswerSchema.objects.create(
                survey=survey, section=section, question=question, type="radio"
            )


# ── AnswerSchemaOption model ────────────────────────────────────
class TestAnswerSchemaOptionModel:
    def test_create_options(self, options):
        assert len(options) == 3
        assert options[0].text == "Red"
        assert options[0].score == 10

    def test_option_auto_order(self, options):
        assert options[0].order == 1
        assert options[1].order == 2
        assert options[2].order == 3

    def test_option_schema_relationship(self, answer_schema, options):
        assert answer_schema.options.count() == 3

    def test_option_with_classification(self, survey, section, question, answer_schema):
        classification = Classification.objects.create(survey=survey, name="Cat A", score=10)
        opt = AnswerSchemaOption.objects.create(
            survey=survey, section=section, question=question,
            schema=answer_schema, text="Opt", classification=classification,
        )
        assert opt.classification == classification

    def test_option_ending_option_flag(self, survey, section, question, answer_schema):
        opt = AnswerSchemaOption.objects.create(
            survey=survey, section=section, question=question,
            schema=answer_schema, text="End", ending_option=True,
        )
        assert opt.ending_option is True


# ── Classification model ────────────────────────────────────────
class TestClassificationModel:
    def test_create_classification(self, survey):
        c = Classification.objects.create(survey=survey, name="High", score=100)
        assert c.name == "High"
        assert c.score == 100
        assert str(c) == "High"

    def test_classification_survey_relationship(self, survey):
        Classification.objects.create(survey=survey, name="A")
        Classification.objects.create(survey=survey, name="B")
        assert survey.classifications.count() == 2


# ── Recommendation model ───────────────────────────────────────
class TestRecommendationModel:
    def test_create_recommendation(self, survey, options):
        r = Recommendation.objects.create(
            survey=survey, option=options[0], description="Try red things"
        )
        assert r.description == "Try red things"
        assert str(r) == "Try red things"

    def test_recommendation_option_relationship(self, survey, options):
        Recommendation.objects.create(survey=survey, option=options[0], description="R1")
        Recommendation.objects.create(survey=survey, option=options[0], description="R2")
        assert options[0].option_recommendations.count() == 2


# ── Action model ────────────────────────────────────────────────
class TestActionModel:
    def test_create_action(self, survey):
        a = Action.objects.create(
            survey=survey, title="Review", description="Review answers",
            upper_limit=100, lower_limit=50,
        )
        assert a.title == "Review"
        assert a.upper_limit == 100.0
        assert a.lower_limit == 50.0

    def test_action_survey_relationship(self, survey):
        Action.objects.create(survey=survey, title="A1")
        Action.objects.create(survey=survey, title="A2")
        assert survey.actions.count() == 2


# ── Usage model ─────────────────────────────────────────────────
class TestUsageModel:
    def test_create_usage(self, user, survey):
        u = Usage.objects.create(
            user=user, survey=survey,
            order_id=uuid.uuid4(), usage_limit=5, used_count=0,
        )
        assert u.usage_limit == 5
        assert u.used_count == 0

    def test_usage_increment(self, user, survey):
        u = Usage.objects.create(
            user=user, survey=survey, order_id=uuid.uuid4(), usage_limit=3, used_count=0,
        )
        u.used_count += 1
        u.save()
        u.refresh_from_db()
        assert u.used_count == 1


# ── Price model ─────────────────────────────────────────────────
class TestPriceModel:
    def test_create_price(self, survey):
        p = Price.objects.create(
            survey=survey, currency="USD", amount_cents=1000,
        )
        assert p.amount_cents == 1000
        assert p.currency == "USD"


# ── Child model ─────────────────────────────────────────────────
class TestChildModel:
    def test_create_child(self):
        child = Child.objects.create(id="child-1", name="Alice")
        assert child.name == "Alice"

    def test_child_with_photo(self):
        child = Child.objects.create(id="child-2", name="Bob", photo_id="photo-123")
        assert child.photo_id == "photo-123"


# ── UserSurvey model ───────────────────────────────────────────
class TestUserSurveyModel:
    def test_create_user_survey(self, user, survey):
        us = UserSurvey.objects.create(user=user, survey=survey)
        assert us.pk is not None
        assert us.submitted_at is None
        assert us.score is None

    def test_user_survey_with_child(self, user, survey):
        child = Child.objects.create(id="child-x", name="Child")
        us = UserSurvey.objects.create(user=user, survey=survey, child=child)
        assert us.child == child

    def test_user_survey_with_collection(self, user, survey, collection):
        us = UserSurvey.objects.create(user=user, survey=survey, collection=collection)
        assert us.collection == collection


# ── UserAnswer model ────────────────────────────────────────────
class TestUserAnswerModel:
    def test_create_user_answer(self, user, survey, question, enrolled_survey):
        ua = UserAnswer.objects.create(
            user=user, survey=survey, question=question,
            user_survey=enrolled_survey, answer="Red", type=question.type,
        )
        assert ua.answer == "Red"
        assert ua.question_title == question.title

    def test_user_answer_with_options(self, user, survey, question, enrolled_survey, options):
        ua = UserAnswer.objects.create(
            user=user, survey=survey, question=question,
            user_survey=enrolled_survey, type=question.type,
        )
        ua.selected_options.set([options[0]])
        assert ua.selected_options.count() == 1


# ── UserSurveyClassification model ─────────────────────────────
class TestUserSurveyClassificationModel:
    def test_create_classification_link(self, enrolled_survey, survey):
        c = Classification.objects.create(survey=survey, name="Class A")
        usc = UserSurveyClassification.objects.create(
            user_survey=enrolled_survey, classification=c, count=3,
        )
        assert usc.count == 3


# ── UserSurveyRecommendation model ─────────────────────────────
class TestUserSurveyRecommendationModel:
    def test_create_recommendation_link(self, enrolled_survey, survey, options):
        r = Recommendation.objects.create(survey=survey, option=options[0], description="R")
        usr = UserSurveyRecommendation.objects.create(
            user_survey=enrolled_survey, recommendation=r, count=2,
        )
        assert usr.count == 2


# ── SurveyCollection model ─────────────────────────────────────
class TestSurveyCollectionModel:
    def test_create_collection(self, collection):
        assert collection.pk is not None
        assert collection.status == SurveyCollection.STATUS_PUBLISHED

    def test_collection_add_survey(self, collection, survey):
        collection.assessments.add(survey)
        assert survey in collection.assessments.all()

    def test_collection_remove_survey(self, collection, survey):
        collection.assessments.add(survey)
        collection.assessments.remove(survey)
        assert survey not in collection.assessments.all()


# ── Category model ──────────────────────────────────────────────
class TestCategoryModel:
    def test_create_category(self, category):
        assert category.name == "Test Category"
        assert str(category) == "Test Category"


# ── Translation models ─────────────────────────────────────────
class TestTranslationModels:
    def test_survey_translation(self, survey):
        t = SurveyTranslation.objects.create(
            survey=survey, language="ar", title="استبيان تجريبي",
        )
        assert t.language == "ar"
        assert t.survey == survey

    def test_section_translation(self, section):
        t = SectionTranslation.objects.create(
            section=section, language="ar", title="القسم الأول",
        )
        assert t.language == "ar"

    def test_question_translation(self, question):
        t = QuestionTranslation.objects.create(
            question=question, language="ar", title="ما هو لونك المفضل؟",
        )
        assert t.language == "ar"

    def test_answer_schema_option_translation(self, options):
        t = AnswerSchemaOptionTranslation.objects.create(
            option=options[0], language="ar", text="أحمر",
        )
        assert t.text == "أحمر"

    def test_classification_translation(self, survey):
        c = Classification.objects.create(survey=survey, name="High")
        t = ClassificationTranslation.objects.create(
            classification=c, language="ar", name="عالي",
        )
        assert t.name == "عالي"

    def test_recommendation_translation(self, survey, options):
        r = Recommendation.objects.create(survey=survey, option=options[0], description="R")
        t = RecommendationTranslation.objects.create(
            recommendation=r, language="ar", description="توصية",
        )
        assert t.description == "توصية"

    def test_action_translation(self, survey):
        a = Action.objects.create(survey=survey, title="Act")
        t = ActionTranslation.objects.create(
            action=a, language="ar", title="إجراء",
        )
        assert t.title == "إجراء"

    def test_category_translation(self, category):
        t = CategoryTranslation.objects.create(
            category=category, language="ar", name="فئة",
        )
        assert t.name == "فئة"

    def test_collection_translation(self, collection):
        t = SurveyCollectionTranslation.objects.create(
            collection=collection, language="ar", title="مجموعة",
        )
        assert t.title == "مجموعة"
