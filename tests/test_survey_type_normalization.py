"""The 0039 retype has to catch every stray `survey_type` and touch nothing else.

`choices` is a form-layer constraint, not a database one, so rows written around
the model kept values no code recognises: `forms` (the route slug) and
`smart_form` (an older editor's name). Both hid the row from the Forms tab and
broke `deleteSurvey` on it. Like 0038, this runs unattended everywhere, so what
it does to already-correct rows matters as much as what it does to the broken
ones.
"""

import importlib

import pytest
from django.apps import apps as django_apps

from surveys.models import Survey

normalize = importlib.import_module(
    "surveys.migrations.0039_normalize_survey_type"
).normalize


def _run():
    normalize(django_apps, None)


@pytest.fixture
def db_(db):
    return db


def test_route_slug_becomes_the_canonical_type(db_):
    survey = Survey.objects.create(survey_type="forms")
    _run()
    survey.refresh_from_db()
    assert survey.survey_type == Survey.ASSESSMENT_TYPE_FORM


def test_smart_form_becomes_the_canonical_type(db_):
    survey = Survey.objects.create(survey_type="smart_form")
    _run()
    survey.refresh_from_db()
    assert survey.survey_type == Survey.ASSESSMENT_TYPE_FORM


def test_valid_types_are_left_alone(db_):
    kept = {
        t: Survey.objects.create(survey_type=t)
        for t, _label in Survey.ASSESSMENT_TYPES
    }
    _run()
    for survey_type, survey in kept.items():
        survey.refresh_from_db()
        assert survey.survey_type == survey_type


def test_a_clean_database_is_unchanged(db_):
    Survey.objects.create(survey_type=Survey.ASSESSMENT_TYPE_SURVEY)
    before = list(Survey.objects.order_by("id").values_list("id", "survey_type"))
    _run()
    assert list(Survey.objects.order_by("id").values_list("id", "survey_type")) == before


def test_every_row_ends_on_a_declared_choice(db_):
    for survey_type in ("forms", "smart_form", "survey", "curriculum"):
        Survey.objects.create(survey_type=survey_type)
    _run()
    declared = {t for t, _label in Survey.ASSESSMENT_TYPES}
    assert set(Survey.objects.values_list("survey_type", flat=True)) <= declared
