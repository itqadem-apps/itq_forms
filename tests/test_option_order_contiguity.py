"""Deleting an answer option must not leave a hole in the order sequence.

Sections and questions have resequenced themselves after a delete since they
were written. Options did not, so removing the third of four choices left the
schema holding 1, 2, 4 permanently — a respondent sees three choices where the
instrument defines four, and nothing in the authoring screens explains it,
because nothing in the authoring screens can produce it. The same absence made
``save`` hand the next new option an order already in use, since it counts the
survivors rather than reading the highest order.
"""

import pytest

from surveys.models import AnswerSchemaOption, Question, Section, Survey


def _orders(schema):
    return list(schema.options.order_by("order", "id").values_list("order", flat=True))


@pytest.fixture
def schema(db):
    survey = Survey.objects.create()
    section = Section.objects.create(survey=survey, title="S", description="")
    question = section.questions.first()  # a signal seeds one
    question.type = Question.QUESTION_TYPE_RADIO_MCQ
    question.save()
    schema = question.answer_schema
    schema.options.all().delete()
    for i in range(1, 5):
        AnswerSchemaOption.objects.create(
            survey=survey, section=section, question=question, schema=schema,
            text=f"choice {i}",
        )
    assert _orders(schema) == [1, 2, 3, 4]
    return schema


def test_deleting_a_middle_option_closes_the_gap(schema):
    schema.options.get(order=3).delete()
    assert _orders(schema) == [1, 2, 3]


def test_the_option_after_the_deleted_one_keeps_its_text(schema):
    """Resequencing renumbers; it must not reshuffle. The survivor that was
    fourth is now third, and it is still the same choice."""
    fourth = schema.options.get(order=4).text
    schema.options.get(order=3).delete()
    assert schema.options.get(order=3).text == fourth


def test_a_new_option_after_a_delete_does_not_collide(schema):
    """``save`` assigns ``count() + 1``. Before resequencing, deleting one of
    four left count at 3, so the new option was given 4 — a tie with the
    survivor, broken arbitrarily by ``Meta.ordering``."""
    schema.options.get(order=3).delete()
    survey = schema.survey
    AnswerSchemaOption.objects.create(
        survey=survey, section_id=schema.section_id,
        question_id=schema.options.first().question_id, schema=schema, text="new",
    )
    orders = _orders(schema)
    assert orders == [1, 2, 3, 4]
    assert len(set(orders)) == len(orders)


def test_deleting_the_last_option_is_already_contiguous(schema):
    schema.options.get(order=4).delete()
    assert _orders(schema) == [1, 2, 3]


def test_options_of_another_schema_are_untouched(schema):
    survey = schema.survey
    other_section = Section.objects.create(survey=survey, title="S2", description="")
    other = other_section.questions.first().answer_schema
    other.options.all().delete()
    for i in range(1, 4):
        AnswerSchemaOption.objects.create(
            survey=survey, section=other_section,
            question=other_section.questions.first(), schema=other, text=f"o{i}",
        )
    schema.options.get(order=2).delete()
    assert _orders(other) == [1, 2, 3]
