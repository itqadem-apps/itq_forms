"""An answer schema's type always follows its question: a type change through
`update_answer_schema` goes through the question, as `update_question` does, and the derived flags
cannot be written directly.

The resolvers are called with their decorators unwrapped, so the test supplies the transaction a
refused write is rolled back in.
"""

import uuid

import pytest
from django.core.exceptions import ValidationError
from django.db import transaction

from surveys.inputs import AnswerSchemaInput, AnswerSchemaOptionInput, QuestionInput
from surveys.models import AnswerSchema, AnswerSchemaOption, Question, Section
from surveys.question_order import renumber_questions
from surveys.schemas.mutations.answer_schemas import AnswerSchemaMutations
from surveys.schemas.mutations.questions import QuestionMutations

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")


def _resolver(cls, name):
    fn = getattr(cls, name)
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def _update_option(option, **fields):
    with transaction.atomic():
        return _resolver(AnswerSchemaMutations, "update_answer_schema_option")(
            AnswerSchemaMutations(), None, id=option.id, input=AnswerSchemaOptionInput(**fields), django_user=None
        )


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


def _question(survey, section, title, type=Question.QUESTION_TYPE_RADIO_MCQ):
    return Question.objects.create(survey=survey, section=section, title=title, type=type)


@pytest.fixture
def tree(survey):
    """Section A holds its default question and `a`, then section B with its default question and `b`."""
    a_sec = Section.objects.create(survey=survey, title="A")
    a = _question(survey, a_sec, "a")
    b_sec = Section.objects.create(survey=survey, title="B")
    b = _question(survey, b_sec, "b")
    sequence = [*a_sec.questions.order_by("id").values_list("id", flat=True),
                *b_sec.questions.order_by("id").values_list("id", flat=True)]
    renumber_questions(survey.id, sequence)
    for q in (a, b):
        q.refresh_from_db()
    return {"a": a, "b": b}


def _shape(question):
    """Question type, schema type, flags, and the (is_row, is_column) of every option, null read as False."""
    q = Question.objects.select_related("answer_schema").get(pk=question.pk)
    s = q.answer_schema
    options = sorted(
        (bool(row), bool(col)) for row, col in AnswerSchemaOption.objects.filter(schema=s).values_list("is_row", "is_column")
    )
    return q.type, s.type, s.is_mcq, s.is_grid, options


def _option_ids(question):
    return set(AnswerSchemaOption.objects.filter(question_id=question.pk).values_list("id", flat=True))


def test_mcq_to_mcq_moves_question_and_schema_and_keeps_options(tree):
    before = _option_ids(tree["a"])
    returned = _update_schema(tree["a"], type=Question.QUESTION_TYPE_CHECKBOX_MCQ)
    q_type, s_type, is_mcq, is_grid, _ = _shape(tree["a"])
    assert (q_type, s_type, is_mcq, is_grid) == ("checkbox", "checkbox", True, False)
    assert _option_ids(tree["a"]) == before
    assert returned.type == "checkbox"


def test_mcq_to_grid_replaces_options_with_one_row_and_one_column(tree):
    returned = _update_schema(tree["a"], type=Question.QUESTION_TYPE_RADIO_GRID)
    assert _shape(tree["a"]) == ("radio_grid", "radio_grid", False, True, [(False, True), (True, False)])
    assert (returned.is_mcq, returned.is_grid) == (False, True)


def test_to_text_clears_flags_and_deletes_options(tree):
    _update_schema(tree["a"], type=Question.QUESTION_TYPE_TEXT)
    assert _shape(tree["a"]) == ("text", "text", False, False, [])


def test_the_same_type_changes_nothing(tree):
    before_shape, before_ids = _shape(tree["a"]), _option_ids(tree["a"])
    _update_schema(tree["a"], type=Question.QUESTION_TYPE_RADIO_MCQ)
    assert _shape(tree["a"]) == before_shape
    assert _option_ids(tree["a"]) == before_ids


def test_a_schema_that_disagrees_with_its_question_is_brought_back_in_step(tree):
    AnswerSchema.objects.filter(question=tree["a"]).update(type=Question.QUESTION_TYPE_CHECKBOX_MCQ)
    _update_schema(tree["a"], type=Question.QUESTION_TYPE_CHECKBOX_MCQ)
    assert _shape(tree["a"])[:2] == ("checkbox", "checkbox")


def test_a_routing_radio_cannot_become_a_checkbox_through_its_schema(tree):
    option = tree["a"].answer_schema.options.first()
    _update_option(option, flow_action="go_to", flow_target_id=str(tree["b"].id))
    before_shape, before_ids = _shape(tree["a"]), _option_ids(tree["a"])
    with pytest.raises(ValidationError) as err:
        _update_schema(tree["a"], type=Question.QUESTION_TYPE_CHECKBOX_MCQ)
    assert "type" in err.value.message_dict
    assert _shape(tree["a"]) == before_shape
    assert _option_ids(tree["a"]) == before_ids


@pytest.mark.parametrize("flag", ["is_mcq", "is_grid"])
@pytest.mark.parametrize("with_type", [False, True])
def test_writing_a_flag_is_refused_and_nothing_is_written(tree, flag, with_type):
    before = _shape(tree["a"])
    fields = {flag: True}
    if with_type:
        fields["type"] = Question.QUESTION_TYPE_RADIO_GRID
    with pytest.raises(ValidationError) as err:
        _update_schema(tree["a"], **fields)
    assert flag in err.value.message_dict
    assert "follows" in err.value.message_dict[flag][0]
    assert _shape(tree["a"]) == before


def test_with_file_alone_is_stored(tree):
    assert AnswerSchema.objects.get(question=tree["a"]).with_file is True
    returned = _update_schema(tree["a"], with_file=False)
    assert AnswerSchema.objects.get(question=tree["a"]).with_file is False
    assert returned.with_file is False


def test_with_file_given_with_a_type_wins_over_the_type_default(tree):
    returned = _update_schema(tree["a"], type=Question.QUESTION_TYPE_CHECKBOX_MCQ, with_file=False)
    stored = AnswerSchema.objects.get(question=tree["a"])
    assert (stored.type, stored.with_file) == ("checkbox", False)
    assert returned.with_file is False


@pytest.mark.parametrize("new_type", [
    Question.QUESTION_TYPE_CHECKBOX_MCQ,
    Question.QUESTION_TYPE_DROPDOWN_MCQ,
    Question.QUESTION_TYPE_RADIO_GRID,
    Question.QUESTION_TYPE_CHECKBOX_GRID,
    Question.QUESTION_TYPE_TEXT,
])
def test_both_mutations_give_the_same_result(survey, tree, new_type):
    via_question = _question(survey, None, "via question")
    via_schema = _question(survey, None, "via schema")
    _update_question(via_question, type=new_type)
    _update_schema(via_schema, type=new_type)
    assert _shape(via_question) == _shape(via_schema)
    assert _shape(via_schema)[:2] == (new_type, new_type)


@pytest.mark.parametrize("bad_type", [None, "slider"])
def test_an_unknown_or_null_type_is_refused_and_nothing_changes(tree, bad_type):
    before_shape, before_ids = _shape(tree["a"]), _option_ids(tree["a"])
    with pytest.raises(ValidationError) as err:
        _update_schema(tree["a"], type=bad_type)
    assert "type" in err.value.message_dict
    assert _shape(tree["a"]) == before_shape
    assert _option_ids(tree["a"]) == before_ids


@pytest.mark.parametrize("flag", ["is_mcq", "is_grid"])
def test_a_null_flag_writes_nothing_and_is_not_refused(tree, flag):
    before = _shape(tree["a"])
    _update_schema(tree["a"], **{flag: None})
    assert _shape(tree["a"]) == before
    _update_schema(tree["a"], **{flag: None, "type": Question.QUESTION_TYPE_CHECKBOX_MCQ})
    assert _shape(tree["a"])[:4] == ("checkbox", "checkbox", True, False)


def test_sending_the_questions_own_type_repairs_a_drifted_schema(tree):
    AnswerSchema.objects.filter(question=tree["a"]).update(
        type=Question.QUESTION_TYPE_RADIO_GRID, is_mcq=False, is_grid=True
    )
    _update_schema(tree["a"], type=Question.QUESTION_TYPE_RADIO_MCQ)
    assert Question.objects.get(pk=tree["a"].pk).type == "radio"
    assert _shape(tree["a"]) == ("radio", "radio", True, False, [(False, False)])


def _change(via, question, new_type):
    (_update_question if via == "question" else _update_schema)(question, type=new_type)


@pytest.mark.parametrize("via", ["question", "schema"])
@pytest.mark.parametrize("start, new_type", [
    (Question.QUESTION_TYPE_TEXT, Question.QUESTION_TYPE_RADIO_MCQ),
    (Question.QUESTION_TYPE_RADIO_GRID, Question.QUESTION_TYPE_CHECKBOX_MCQ),
])
def test_becoming_mcq_leaves_exactly_one_plain_option_on_the_schema(survey, tree, via, start, new_type):
    q = _question(survey, None, "q")
    _update_question(q, type=start)
    _change(via, q, new_type)
    schema = AnswerSchema.objects.get(question=q)
    options = list(AnswerSchemaOption.objects.filter(question=q).values_list("schema_id", "is_row", "is_column"))
    assert [(sid, bool(row), bool(col)) for sid, row, col in options] == [(schema.id, False, False)]
    assert (schema.type, schema.is_mcq, schema.is_grid) == (new_type, True, False)
