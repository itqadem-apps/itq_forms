"""Story survey-flow 2.1 — an answer option names the next question or ends the survey (`forms:AD-3`,
`forms:AD-5`).

The resolvers are called with their decorators unwrapped, so the test supplies the transaction a
refused write is rolled back in.
"""

import uuid
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from surveys.inputs import AnswerSchemaInput, AnswerSchemaOptionInput, QuestionInput, QuestionPlacementInput
from surveys.models import AnswerSchemaOption, FlowAction, Question, Section, Survey
from surveys.question_order import renumber_questions
from surveys.schemas.mutations.answer_schemas import AnswerSchemaMutations
from surveys.schemas.mutations.questions import QuestionMutations
from surveys.schemas.mutations.surveys import SurveyMutations
from user_surveys.models import UserAnswerOption
from user_surveys.services import enroll_user_in_assessment

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")


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


def _create(schema, **fields):
    with transaction.atomic():
        return _resolver(AnswerSchemaMutations, "create_answer_schema_option")(
            AnswerSchemaMutations(), None, schema_id=schema.id, input=AnswerSchemaOptionInput(**fields), django_user=None
        )


def _question(survey, section, title, type=Question.QUESTION_TYPE_RADIO_MCQ):
    return Question.objects.create(survey=survey, section=section, title=title, type=type)


@pytest.fixture
def tree(survey):
    """Section A holds its default question and `a`, then sectionless `free`, then section B with its
    default question and `b`."""
    a_sec = Section.objects.create(survey=survey, title="A")
    a = _question(survey, a_sec, "a")
    free = _question(survey, None, "free")
    b_sec = Section.objects.create(survey=survey, title="B")
    b = _question(survey, b_sec, "b")
    sequence = [*a_sec.questions.order_by("id").values_list("id", flat=True), free.id,
                *b_sec.questions.order_by("id").values_list("id", flat=True)]
    renumber_questions(survey.id, sequence)
    for q in (a, free, b):
        q.refresh_from_db()
    return {"a": a, "free": free, "b": b, "a_sec": a_sec, "b_sec": b_sec}


def _option(question):
    return question.answer_schema.options.first()


def _stored(option):
    return AnswerSchemaOption.objects.values_list("flow_action", "flow_target_id").get(pk=option.pk)


# ── Columns ─────────────────────────────────────────────────────


def test_a_new_option_stores_fall_through_explicitly(tree):
    option = _create(tree["a"].answer_schema, text="new")
    assert _stored(option) == ("fall_through", None)
    assert AnswerSchemaOption.objects.filter(flow_action__isnull=True).count() == 0


def test_the_snapshot_option_carries_the_same_columns(survey, tree, user):
    us, _ = enroll_user_in_assessment(user, survey.id)
    rows = set(UserAnswerOption.objects.filter(user_survey=us).values_list("flow_action", "flow_target_id"))
    assert rows == {("fall_through", None)}


# ── An edge is stored ───────────────────────────────────────────


def test_go_to_names_a_later_question_in_another_section(tree):
    option = _update(_option(tree["a"]), flow_action="go_to", flow_target_id=str(tree["b"].id))
    assert _stored(option) == ("go_to", tree["b"].id)


def test_go_to_may_target_a_sectionless_question(tree):
    _update(_option(tree["a"]), flow_action="go_to", flow_target_id=str(tree["free"].id))
    assert _stored(_option(tree["a"])) == ("go_to", tree["free"].id)


def test_terminate_needs_no_target(tree):
    _update(_option(tree["a"]), flow_action="terminate")
    assert _stored(_option(tree["a"])) == ("terminate", None)


def test_an_edge_can_be_set_on_create(tree):
    option = _create(tree["a"].answer_schema, text="skip", flow_action="go_to", flow_target_id=str(tree["b"].id))
    assert _stored(option) == ("go_to", tree["b"].id)


# ── Refusals ────────────────────────────────────────────────────


def _refused(option, field, **fields):
    before = _stored(option)
    with pytest.raises(ValidationError) as err:
        _update(option, **fields)
    assert field in err.value.message_dict
    assert _stored(option) == before


def test_go_to_without_a_target_is_refused(tree):
    _refused(_option(tree["a"]), "flow_target_id", flow_action="go_to")


@pytest.mark.parametrize("action", ["fall_through", "terminate"])
def test_a_target_on_any_other_action_is_refused(tree, action):
    _refused(_option(tree["a"]), "flow_target_id", flow_action=action, flow_target_id=str(tree["b"].id))


def test_an_unknown_action_is_refused(tree):
    _refused(_option(tree["a"]), "flow_action", flow_action="jump")


def test_a_backward_edge_is_refused_and_nothing_is_stored(tree):
    _refused(_option(tree["b"]), "flow_target_id", flow_action="go_to", flow_target_id=str(tree["a"].id))


def test_an_edge_to_its_own_question_is_refused(tree):
    _refused(_option(tree["a"]), "flow_target_id", flow_action="go_to", flow_target_id=str(tree["a"].id))


def test_a_target_in_another_survey_is_refused(tree):
    other = Survey.objects.create(organization_id=ORG)
    stranger = Question.objects.create(survey=other, title="x")
    _refused(_option(tree["a"]), "flow_target_id", flow_action="go_to", flow_target_id=str(stranger.id))


@pytest.mark.parametrize("type", [Question.QUESTION_TYPE_CHECKBOX_MCQ, Question.QUESTION_TYPE_RADIO_GRID, Question.QUESTION_TYPE_CHECKBOX_GRID])
@pytest.mark.parametrize("fields", [{"flow_action": "terminate"}, {"flow_action": "go_to", "flow_target_id": "B"}])
def test_a_multi_answer_question_cannot_route(survey, tree, type, fields):
    multi = _question(survey, tree["a_sec"], "multi", type=type)
    option = multi.answer_schema.options.first() or AnswerSchemaOption.objects.create(
        survey=survey, question=multi, schema=multi.answer_schema, text="o"
    )
    if fields.get("flow_target_id") == "B":
        fields = {**fields, "flow_target_id": str(tree["b"].id)}
    _refused(option, "flow_action", **fields)


def test_a_dropdown_question_can_route(survey, tree):
    drop = _question(survey, tree["a_sec"], "drop", type=Question.QUESTION_TYPE_DROPDOWN_MCQ)
    option = drop.answer_schema.options.first() or AnswerSchemaOption.objects.create(
        survey=survey, question=drop, schema=drop.answer_schema, text="o"
    )
    _update(option, flow_action="terminate")
    assert _stored(option) == ("terminate", None)


# ── The one predicate, after the write ──────────────────────────


def test_a_reorder_that_would_put_the_target_first_is_refused(survey, tree):
    _update(_option(tree["a"]), flow_action="go_to", flow_target_id=str(tree["free"].id))
    order = list(Question.objects.filter(survey=survey).order_by("order").values_list("id", "section_id"))
    free = (tree["free"].id, None)
    moved = [free] + [row for row in order if row != free]
    placements = [QuestionPlacementInput(question_id=str(pk), section_id=str(sid) if sid else None) for pk, sid in moved]

    with pytest.raises(ValidationError) as err:
        with transaction.atomic():
            _resolver(QuestionMutations, "reorder_survey_questions")(
                QuestionMutations(), None, survey_id=survey.id, placements=placements, django_user=None
            )
    assert "placements" in err.value.message_dict
    assert list(Question.objects.filter(survey=survey).order_by("order").values_list("id", "section_id")) == order


# ── Deletion and copies ─────────────────────────────────────────


def test_deleting_the_target_makes_the_edge_fall_through(tree):
    _update(_option(tree["a"]), flow_action="go_to", flow_target_id=str(tree["b"].id))
    tree["b"].delete()
    assert _stored(_option(tree["a"])) == ("fall_through", None)


def test_a_duplicated_question_starts_with_no_flow(tree):
    _update(_option(tree["a"]), flow_action="go_to", flow_target_id=str(tree["b"].id))
    copy = _resolver(QuestionMutations, "duplicate_question")(QuestionMutations(), None, id=tree["a"].id, django_user=None)
    assert set(copy.answer_schema.options.values_list("flow_action", "flow_target_id")) == {("fall_through", None)}
    assert _stored(_option(tree["a"])) == ("go_to", tree["b"].id)


# duplicate_survey has failed since b3e6376: the post_save signals give every cloned question an
# AnswerSchema, then the explicit clone inserts a second one. Strict, so the fix flips this red.
@pytest.mark.xfail(raises=IntegrityError, strict=True, reason="duplicate_survey clones a schema the signal already created")
def test_a_duplicated_survey_points_its_edges_at_its_own_questions(survey, tree, monkeypatch):
    monkeypatch.setattr("surveys.schemas.mutations.surveys.ensure_in_org", lambda *a, **k: None)
    _update(_option(tree["a"]), flow_action="go_to", flow_target_id=str(tree["b"].id))

    info = SimpleNamespace(context=SimpleNamespace(auth_context=None))
    payload = _resolver(SurveyMutations, "duplicate_survey")(SurveyMutations(), info, id=survey.id, django_user=None)

    copy = payload.survey
    edge = AnswerSchemaOption.objects.get(survey=copy, flow_action=FlowAction.GO_TO)
    assert edge.flow_target.survey_id == copy.id
    assert edge.flow_target.title == "b"
    assert edge.question.title == "a"


# ── A routing question keeps a type that can route ──────────────


def _update_question(question, **fields):
    with transaction.atomic():
        return _resolver(QuestionMutations, "update_question")(
            QuestionMutations(), None, id=question.id, input=QuestionInput(**fields), django_user=None
        )


def _update_schema(question, **fields):
    with transaction.atomic():
        return _resolver(AnswerSchemaMutations, "update_answer_schema")(
            AnswerSchemaMutations(), None, id=question.answer_schema.id, input=AnswerSchemaInput(**fields), django_user=None
        )


def _shape(question):
    q = Question.objects.select_related("answer_schema").get(pk=question.pk)
    edges = set(AnswerSchemaOption.objects.filter(question=q).values_list("flow_action", "flow_target_id"))
    return q.type, q.answer_schema.type, AnswerSchemaOption.objects.filter(question=q).count(), edges


def _type_change_refused(change, question, new_type):
    before = _shape(question)
    with pytest.raises(ValidationError) as err:
        change(question, type=new_type)
    assert "type" in err.value.message_dict
    assert "go_to and terminate options" in err.value.message_dict["type"][0]
    assert _shape(question) == before


def test_a_routing_radio_cannot_become_a_checkbox(tree):
    _update(_option(tree["a"]), flow_action="go_to", flow_target_id=str(tree["b"].id))
    _type_change_refused(_update_question, tree["a"], Question.QUESTION_TYPE_CHECKBOX_MCQ)


def test_a_routing_radio_cannot_become_a_checkbox_through_its_schema(tree):
    _update(_option(tree["a"]), flow_action="go_to", flow_target_id=str(tree["b"].id))
    _type_change_refused(_update_schema, tree["a"], Question.QUESTION_TYPE_CHECKBOX_MCQ)


def test_a_terminate_option_counts_as_routing(tree):
    _update(_option(tree["a"]), flow_action="terminate")
    _type_change_refused(_update_question, tree["a"], Question.QUESTION_TYPE_CHECKBOX_MCQ)


@pytest.mark.parametrize("new_type", [Question.QUESTION_TYPE_TEXT, Question.QUESTION_TYPE_RADIO_GRID])
def test_a_routing_radio_cannot_become_a_type_that_drops_its_options(tree, new_type):
    _update(_option(tree["a"]), flow_action="go_to", flow_target_id=str(tree["b"].id))
    _type_change_refused(_update_question, tree["a"], new_type)


def test_a_routing_radio_can_become_a_dropdown(tree):
    _update(_option(tree["a"]), flow_action="go_to", flow_target_id=str(tree["b"].id))
    _update_question(tree["a"], type=Question.QUESTION_TYPE_DROPDOWN_MCQ)
    assert _shape(tree["a"]) == ("dropdown", "dropdown", 1, {("go_to", tree["b"].id)})


def test_a_radio_that_does_not_route_can_become_a_checkbox(tree):
    _update_question(tree["a"], type=Question.QUESTION_TYPE_CHECKBOX_MCQ)
    assert _shape(tree["a"])[:2] == ("checkbox", "checkbox")


def test_a_radio_whose_edges_were_removed_can_become_a_checkbox(tree):
    _update(_option(tree["a"]), flow_action="go_to", flow_target_id=str(tree["b"].id))
    _update(_option(tree["a"]), flow_action="fall_through", flow_target_id=None)
    _update_question(tree["a"], type=Question.QUESTION_TYPE_CHECKBOX_MCQ)
    assert _shape(tree["a"]) == ("checkbox", "checkbox", 1, {("fall_through", None)})


def test_an_update_that_leaves_the_type_alone_is_allowed(tree):
    _update(_option(tree["a"]), flow_action="go_to", flow_target_id=str(tree["b"].id))
    _update_question(tree["a"], title="renamed")
    assert Question.objects.get(pk=tree["a"].pk).title == "renamed"
    assert _shape(tree["a"]) == ("radio", "radio", 1, {("go_to", tree["b"].id)})


def test_a_routing_radio_can_become_a_dropdown_through_its_schema(tree):
    _update(_option(tree["a"]), flow_action="go_to", flow_target_id=str(tree["b"].id))
    _update_schema(tree["a"], type=Question.QUESTION_TYPE_DROPDOWN_MCQ)
    assert AnswerSchemaOption.objects.filter(question=tree["a"]).count() == 1
    assert set(AnswerSchemaOption.objects.filter(question=tree["a"]).values_list("flow_action", "flow_target_id")) == {
        ("go_to", tree["b"].id)
    }
    assert Question.objects.get(pk=tree["a"].pk).answer_schema.type == "dropdown"
