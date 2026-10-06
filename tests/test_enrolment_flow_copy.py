"""Story survey-flow 2.2 — the enrolment copy carries the flow (`forms:AD-2`, `forms:AD-3`,
`forms:AD-5`)."""

import pytest
from django.core.exceptions import ValidationError

from surveys.models import AnswerSchemaOption, FlowAction, Question, Section, Survey
from surveys.question_order import renumber_questions
from user_surveys.models import UserAnswerOption, UserQuestion, UserSurvey
from user_surveys.services import enroll_user_in_assessment


def _question(survey, section, title):
    return Question.objects.create(survey=survey, section=section, title=title, type=Question.QUESTION_TYPE_RADIO_MCQ)


@pytest.fixture
def tree(survey):
    a_sec = Section.objects.create(survey=survey, title="A")
    a = _question(survey, a_sec, "a")
    free = _question(survey, None, "free")
    b_sec = Section.objects.create(survey=survey, title="B")
    b = _question(survey, b_sec, "b")
    renumber_questions(survey.id, [*a_sec.questions.order_by("id").values_list("id", flat=True), free.id,
                                   *b_sec.questions.order_by("id").values_list("id", flat=True)])
    return {"a": a, "free": free, "b": b}


def _route(question, action, target=None):
    """Writes the columns directly: validation is story 2.1's, and is tested there."""
    option = question.answer_schema.options.first()
    AnswerSchemaOption.objects.filter(pk=option.pk).update(flow_action=action, flow_target=target)
    return option


def _snapshot_option(us, option):
    return UserAnswerOption.objects.select_related("flow_target").get(user_survey=us, origin_id=option.id)


def test_go_to_is_copied_onto_the_learners_own_question(survey, tree, user):
    option = _route(tree["a"], FlowAction.GO_TO, tree["b"])
    us, _ = enroll_user_in_assessment(user, survey.id)

    copy = _snapshot_option(us, option)
    assert copy.flow_action == "go_to"
    assert copy.flow_target.user_survey_id == us.id
    assert copy.flow_target.origin_id == tree["b"].id


def test_a_sectionless_target_is_remapped_too(survey, tree, user):
    option = _route(tree["a"], FlowAction.GO_TO, tree["free"])
    us, _ = enroll_user_in_assessment(user, survey.id)
    assert _snapshot_option(us, option).flow_target.origin_id == tree["free"].id


def test_terminate_and_fall_through_copy_without_a_target(survey, tree, user):
    end = _route(tree["a"], FlowAction.TERMINATE)
    us, _ = enroll_user_in_assessment(user, survey.id)

    assert (_snapshot_option(us, end).flow_action, _snapshot_option(us, end).flow_target_id) == ("terminate", None)
    others = UserAnswerOption.objects.filter(user_survey=us).exclude(origin_id=end.id)
    assert set(others.values_list("flow_action", "flow_target_id")) == {("fall_through", None)}


def test_each_learner_gets_their_own_target_row(survey, tree, user, user2):
    option = _route(tree["a"], FlowAction.GO_TO, tree["b"])
    first, _ = enroll_user_in_assessment(user, survey.id)
    second, _ = enroll_user_in_assessment(user2, survey.id)

    assert _snapshot_option(first, option).flow_target_id != _snapshot_option(second, option).flow_target_id


def test_an_author_edit_after_enrolment_does_not_reach_the_learner(survey, tree, user):
    option = _route(tree["a"], FlowAction.GO_TO, tree["b"])
    us, _ = enroll_user_in_assessment(user, survey.id)

    b_id = tree["b"].id
    _route(tree["a"], FlowAction.TERMINATE)
    tree["b"].delete()

    copy = _snapshot_option(us, option)
    assert (copy.flow_action, copy.flow_target.origin_id) == ("go_to", b_id)


def test_the_snapshot_order_is_checked_forward_after_the_copy(survey, tree, user, monkeypatch):
    """By construction the copy passes (story 2.6 keeps a shuffle from breaking it); this forces a
    backward snapshot to prove the check runs and the enrolment rolls back whole."""
    _route(tree["a"], FlowAction.GO_TO, tree["b"])
    monkeypatch.setattr(
        "user_surveys.services.flat_question_ids", lambda qs: list(qs.order_by("-order").values_list("id", flat=True))
    )

    with pytest.raises(ValidationError) as err:
        enroll_user_in_assessment(user, survey.id)
    assert "flow_target" in err.value.message_dict
    assert not UserSurvey.objects.filter(user=user, survey=survey).exists()
    assert not UserQuestion.objects.filter(user_survey__user=user).exists()


def test_a_target_outside_the_copy_raises_instead_of_dangling(survey, tree, user):
    """Validation keeps a target inside its survey; a row written around it is corrupt data."""
    other = Survey.objects.create(organization_id=survey.organization_id)
    stranger = Question.objects.create(survey=other, title="x")
    option = _route(tree["a"], FlowAction.GO_TO, stranger)

    with pytest.raises(ValueError, match=f"routes to question {stranger.id}"):
        enroll_user_in_assessment(user, survey.id)
    assert not UserAnswerOption.objects.filter(origin_id=option.id).exists()


def test_a_survey_without_flow_enrols_exactly_as_before(survey, tree, user):
    us, _ = enroll_user_in_assessment(user, survey.id)
    assert UserQuestion.objects.filter(user_survey=us).count() == Question.objects.filter(survey=survey).count()
    assert not UserAnswerOption.objects.filter(user_survey=us).exclude(flow_action="fall_through").exists()
