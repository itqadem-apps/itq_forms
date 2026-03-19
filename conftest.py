import os
import uuid

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
os.environ["DATABASE_ENGINE"] = "django.db.backends.sqlite3"
os.environ["DATABASE_NAME"] = ":memory:"


@pytest.fixture(autouse=True)
def _use_db(db):
    """Ensure every test has database access."""
    pass


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    return User.objects.create(
        id=f"keycloak-{uuid.uuid4().hex[:12]}",
        username="testuser",
        email="test@example.com",
    )


@pytest.fixture
def user2(db):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    return User.objects.create(
        id=f"keycloak-{uuid.uuid4().hex[:12]}",
        username="testuser2",
        email="test2@example.com",
    )


@pytest.fixture
def survey(db):
    from surveys.models import Survey, SurveyTranslation
    s = Survey.objects.create(
        survey_type=Survey.ASSESSMENT_TYPE_SURVEY,
        display_option=Survey.DISPLAY_OPTION_BY_QUESTION,
        evaluation_type=Survey.EVALUATION_TYPE_AUTOMATIC_EVALUATION,
        use_score=True,
        use_classifications=False,
        use_recommendations=False,
        use_actions=False,
    )
    SurveyTranslation.objects.create(
        survey=s,
        language="en",
        title="Test Survey",
        description="A test survey",
        short_description="Short desc",
    )
    return s


@pytest.fixture
def section(survey):
    """Create a section. NOTE: a signal auto-creates a default Question + AnswerSchema + Option."""
    from surveys.models import Section
    return Section.objects.create(
        survey=survey,
        title="Section 1",
        description="First section",
    )


@pytest.fixture
def question(survey, section):
    """Use the auto-created question from the section signal, update it for our tests."""
    from surveys.models import Question
    # The section signal auto-creates a question; grab and customize it
    q = section.questions.first()
    q.title = "What is your favorite color?"
    q.type = Question.QUESTION_TYPE_RADIO_MCQ
    q.is_required = True
    q.save()
    return q


@pytest.fixture
def answer_schema(question):
    """Return the auto-created answer schema from the question signal."""
    return question.answer_schema


@pytest.fixture
def options(survey, section, question, answer_schema):
    """Create test options. Clears auto-created default options first."""
    from surveys.models import AnswerSchemaOption
    answer_schema.options.all().delete()
    opt_a = AnswerSchemaOption.objects.create(
        survey=survey, section=section, question=question,
        schema=answer_schema, text="Red", score=10,
    )
    opt_b = AnswerSchemaOption.objects.create(
        survey=survey, section=section, question=question,
        schema=answer_schema, text="Blue", score=20,
    )
    opt_c = AnswerSchemaOption.objects.create(
        survey=survey, section=section, question=question,
        schema=answer_schema, text="Green", score=30,
    )
    return [opt_a, opt_b, opt_c]


@pytest.fixture
def enrolled_survey(user, survey, section, question, options):
    from user_surveys.services import enroll_user_in_assessment
    user_survey, _ = enroll_user_in_assessment(user, survey.id)
    return user_survey


@pytest.fixture
def category(db):
    from taxonomy.models import Category
    return Category.objects.create(
        tree_id=uuid.uuid4(),
        name="Test Category",
    )


@pytest.fixture
def collection(db):
    from survey_collections.models import SurveyCollection, SurveyCollectionTranslation
    c = SurveyCollection.objects.create(
        status=SurveyCollection.STATUS_PUBLISHED,
    )
    SurveyCollectionTranslation.objects.create(
        collection=c,
        language="en",
        title="Test Collection",
        description="A collection",
    )
    return c
