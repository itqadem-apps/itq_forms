"""Story survey-flow 2.6 — shuffle and the flow coexist (`forms:AD-12`)."""

import random

import pytest
from django.core.exceptions import ValidationError

from surveys.models import AnswerSchemaOption, FlowAction, Question, Section, ShuffleScope, Survey
from surveys.question_order import flat_question_ids, renumber_questions, split_sections
from surveys.schemas.mutations.surveys import _check_shuffle_scope
from surveys.types.survey import SurveyType
from user_surveys.models import UserQuestion
from user_surveys.services import _shuffle_questions, enroll_user_in_assessment


def _question(survey, section, title):
    return Question.objects.create(survey=survey, section=section, title=title, type=Question.QUESTION_TYPE_RADIO_MCQ)


def _route(question, action, target=None):
    option = question.answer_schema.options.first()
    AnswerSchemaOption.objects.filter(pk=option.pk).update(flow_action=action, flow_target=target)


@pytest.fixture
def tree(survey):
    """A: [default, a1, a2, a3] · free1 · free2 · B: [default, b1, b2]."""
    a_sec = Section.objects.create(survey=survey, title="A")
    a = [_question(survey, a_sec, f"a{i}") for i in (1, 2, 3)]
    free = [_question(survey, None, f"free{i}") for i in (1, 2)]
    b_sec = Section.objects.create(survey=survey, title="B")
    b = [_question(survey, b_sec, f"b{i}") for i in (1, 2)]
    renumber_questions(survey.id, [
        *a_sec.questions.order_by("id").values_list("id", flat=True),
        *(q.id for q in free),
        *b_sec.questions.order_by("id").values_list("id", flat=True),
    ])
    Survey.objects.filter(pk=survey.pk).update(randomize_questions=True)
    return {"a": a, "free": free, "b": b}


def _origins(us):
    """The learner's walk order, as author-side question ids."""
    snapshot = UserQuestion.objects.filter(user_survey=us)
    origin = dict(snapshot.values_list("id", "origin_id"))
    return [origin[pk] for pk in flat_question_ids(snapshot)]


def _reshuffle(us, times=40):
    for seed in range(times):
        random.seed(seed)
        _shuffle_questions(us)
        yield _origins(us)


def _sections_contiguous(us):
    snapshot = UserQuestion.objects.filter(user_survey=us)
    return not split_sections(flat_question_ids(snapshot), dict(snapshot.values_list("id", "section_id")))


def test_anchors_keep_their_place_and_every_gap_keeps_its_questions(survey, tree, user):
    a1, b1 = tree["a"][0], tree["b"][0]
    _route(a1, FlowAction.GO_TO, b1)
    us, _ = enroll_user_in_assessment(user, survey.id)
    authored = list(Question.objects.filter(survey=survey).order_by("order").values_list("id", flat=True))
    at = {pk: i for i, pk in enumerate(authored)}

    orders = list(_reshuffle(us))
    for order in orders:
        assert order.index(a1.id) == at[a1.id]
        assert order.index(b1.id) == at[b1.id]
        # What a1 → b1 skips is the same stretch for every learner.
        assert set(order[at[a1.id] + 1:at[b1.id]]) == set(authored[at[a1.id] + 1:at[b1.id]])
        assert _sections_contiguous(us)
    assert len({tuple(o) for o in orders}) > 1


def test_a_question_never_leaves_its_section_group(survey, tree, user):
    _route(tree["a"][0], FlowAction.GO_TO, tree["b"][0])
    us, _ = enroll_user_in_assessment(user, survey.id)
    section_of = dict(Question.objects.filter(survey=survey).values_list("id", "section_id"))
    authored = list(Question.objects.filter(survey=survey).order_by("order").values_list("id", flat=True))

    for order in _reshuffle(us):
        assert [section_of[pk] for pk in order] == [section_of[pk] for pk in authored]


def test_a_terminating_question_is_an_anchor(survey, tree, user):
    a2 = tree["a"][1]
    _route(a2, FlowAction.TERMINATE)
    us, _ = enroll_user_in_assessment(user, survey.id)
    authored = list(Question.objects.filter(survey=survey).order_by("order").values_list("id", flat=True))

    for order in _reshuffle(us):
        assert order.index(a2.id) == authored.index(a2.id)
        assert set(order[:authored.index(a2.id)]) == set(authored[:authored.index(a2.id)])


def test_a_flow_with_shuffle_enrols_every_time(survey, tree, django_user_model):
    """Story 2.2's forward-only check runs on every enrolment; the anchors make it pass."""
    _route(tree["a"][0], FlowAction.GO_TO, tree["b"][0])
    _route(tree["free"][0], FlowAction.GO_TO, tree["b"][1])
    for i in range(25):
        learner = django_user_model.objects.create(id=f"learner-{i}", username=f"learner{i}", email=f"l{i}@example.com")
        enroll_user_in_assessment(learner, survey.id)


def test_without_a_flow_every_question_shuffles_within_its_section_group(survey, tree, user):
    us, _ = enroll_user_in_assessment(user, survey.id)
    section_of = dict(Question.objects.filter(survey=survey).values_list("id", "section_id"))
    authored = list(Question.objects.filter(survey=survey).order_by("order").values_list("id", flat=True))

    orders = list(_reshuffle(us))
    for order in orders:
        assert [section_of[pk] for pk in order] == [section_of[pk] for pk in authored]
    moved = {pk for o in orders for i, pk in enumerate(o) if authored[i] != pk}
    assert moved >= {q.id for q in (*tree["a"], *tree["b"], *tree["free"])}


def test_no_shuffle_keeps_the_authored_order(survey, tree, user):
    Survey.objects.filter(pk=survey.pk).update(randomize_questions=False)
    us, _ = enroll_user_in_assessment(user, survey.id)
    assert _origins(us) == list(Question.objects.filter(survey=survey).order_by("order").values_list("id", flat=True))


def test_the_scope_defaults_to_untouched_and_is_snapshotted(survey, tree, user):
    assert Survey.objects.get(pk=survey.pk).shuffle_scope == ShuffleScope.UNTOUCHED
    Survey.objects.filter(pk=survey.pk).update(shuffle_scope=ShuffleScope.ALL)
    us, _ = enroll_user_in_assessment(user, survey.id)
    assert us.shuffle_scope == "all"


def test_an_unknown_scope_is_refused():
    _check_shuffle_scope({"shuffle_scope": "all"})
    _check_shuffle_scope({})
    with pytest.raises(ValidationError) as err:
        _check_shuffle_scope({"shuffle_scope": "some"})
    assert "shuffle_scope" in err.value.message_dict
    # A sent null would reach the NOT NULL column.
    with pytest.raises(ValidationError):
        _check_shuffle_scope({"shuffle_scope": None})


def _has_flow(survey):
    field = next(f for f in SurveyType.__strawberry_definition__.fields if f.python_name == "has_flow")
    return field.base_resolver.wrapped_func(survey)


def test_has_flow_tells_the_builder_when_all_and_untouched_coincide(survey, tree):
    assert _has_flow(survey) is False
    _route(tree["a"][1], FlowAction.TERMINATE)
    assert _has_flow(survey) is True
