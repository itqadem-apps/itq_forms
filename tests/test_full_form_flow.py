"""Story survey-flow 2.4 — no flow on a one-page form (`forms:AD-11`)."""

import pytest
from django.core.exceptions import ValidationError
from django.db import transaction

from surveys.flow import check_display_option
from surveys.inputs import AnswerSchemaOptionInput
from surveys.models import AnswerSchemaOption, FlowAction, Question, Survey
from surveys.schemas.mutations.answer_schemas import AnswerSchemaMutations

FULL_FORM = Survey.DISPLAY_OPTION_FULL_FORM


def _resolver(cls, name):
    fn = getattr(cls, name)
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def _update(option, **fields):
    with transaction.atomic():
        return _resolver(AnswerSchemaMutations, "update_answer_schema_option")(
            AnswerSchemaMutations(), None, id=option.id, input=AnswerSchemaOptionInput(**fields), django_user=None
        )


@pytest.fixture
def pair(survey):
    a = Question.objects.create(survey=survey, title="a", type=Question.QUESTION_TYPE_RADIO_MCQ)
    b = Question.objects.create(survey=survey, title="b", type=Question.QUESTION_TYPE_RADIO_MCQ)
    return a, b


def _option(question):
    return question.answer_schema.options.first()


@pytest.mark.parametrize("action", [FlowAction.GO_TO, FlowAction.TERMINATE])
def test_an_edge_on_a_full_form_survey_is_refused(survey, pair, action):
    Survey.objects.filter(pk=survey.pk).update(display_option=FULL_FORM)
    a, b = pair
    target = str(b.id) if action == FlowAction.GO_TO else None

    with pytest.raises(ValidationError) as err:
        _update(_option(a), flow_action=action, flow_target_id=target)
    assert "full_form" in " ".join(err.value.message_dict["flow_action"])
    assert AnswerSchemaOption.objects.get(pk=_option(a).pk).flow_action == FlowAction.FALL_THROUGH


def test_fall_through_stays_writable_on_full_form(survey, pair):
    Survey.objects.filter(pk=survey.pk).update(display_option=FULL_FORM)
    _update(_option(pair[0]), flow_action=FlowAction.FALL_THROUGH)


def test_switching_a_survey_with_a_flow_to_full_form_is_refused(survey, pair):
    _update(_option(pair[0]), flow_action=FlowAction.TERMINATE)
    survey.refresh_from_db()

    with pytest.raises(ValidationError) as err:
        check_display_option(survey, FULL_FORM)
    assert "display_option" in err.value.message_dict


def test_a_survey_without_a_flow_switches_freely(survey, pair):
    check_display_option(survey, FULL_FORM)
    check_display_option(survey, Survey.DISPLAY_OPTION_BY_SECTION)


def test_editing_a_full_form_survey_without_a_flow_changes_nothing(survey, pair):
    Survey.objects.filter(pk=survey.pk).update(display_option=FULL_FORM)
    survey.refresh_from_db()
    check_display_option(survey, FULL_FORM)
    check_display_option(survey, None)
