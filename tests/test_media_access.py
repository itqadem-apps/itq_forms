"""_collect_restricted_asset_ids must return every asset the survey owns.

Grant, revoke, promote and demote all act on exactly this list, so it is the
single point where a restricted survey asset becomes reachable. Two defects met
here: the option lookup walked `answer_schema__question__section__survey_id`,
which names no field (the FK is `schema`), so every call raised FieldError
before it reached the media client; and question covers were never collected at
all, so they were never granted to a buyer nor promoted on publish.
"""
from surveys.media_access import _collect_restricted_asset_ids
from surveys.models import Survey, Section, Question, AnswerSchemaOption


def test_collects_section_question_and_option_assets(survey, section, question):
    section.cover_asset_id = "sec-1"
    section.save()

    question.cover_asset_id = "que-1"
    question.save()

    option = question.answer_schema.options.first()
    option.image_asset_id = "opt-1"
    option.save()

    assert set(_collect_restricted_asset_ids(survey.pk)) == {"sec-1", "que-1", "opt-1"}


def test_question_cover_is_collected(survey, question):
    """The regression on its own: a survey whose only asset is a question cover."""
    question.cover_asset_id = "que-only"
    question.save()

    assert _collect_restricted_asset_ids(survey.pk) == ["que-only"]


def test_option_lookup_resolves(survey, question):
    """The FieldError: this raised before it could return anything at all."""
    option = question.answer_schema.options.first()
    option.image_asset_id = "opt-only"
    option.save()

    assert _collect_restricted_asset_ids(survey.pk) == ["opt-only"]


def test_ignores_null_assets(survey, question):
    assert _collect_restricted_asset_ids(survey.pk) == []


def test_scopes_to_the_named_survey(survey, question):
    other = Survey.objects.create()
    other_section = Section.objects.create(survey=other, title="Elsewhere")
    other_question = other_section.questions.first()
    other_question.cover_asset_id = "elsewhere"
    other_question.save()

    assert "elsewhere" not in _collect_restricted_asset_ids(survey.pk)
