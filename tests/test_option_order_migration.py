"""The 0038 sweep must close existing holes without disturbing anything else.

Prod cannot run a management command, so the one-off repair rides in as a data
migration. It runs unattended, on every environment, with nobody reading the
output — so what it does to a *clean* schema matters as much as what it does to
a broken one.
"""

import importlib

import pytest
from django.apps import apps as django_apps

from surveys.models import AnswerSchemaOption, Question, Section, Survey

close_holes = importlib.import_module(
    "surveys.migrations.0038_close_option_order_holes"
).close_holes


def _run():
    close_holes(django_apps, None)


def _orders(schema):
    return list(schema.options.order_by("order", "id").values_list("order", flat=True))


def _schema(survey, title):
    section = Section.objects.create(survey=survey, title=title, description="")
    question = section.questions.first()
    question.type = Question.QUESTION_TYPE_RADIO_MCQ
    question.save()
    schema = question.answer_schema
    schema.options.all().delete()
    return section, question, schema


@pytest.fixture
def survey(db):
    return Survey.objects.create()


def test_a_hole_is_closed(survey):
    section, question, schema = _schema(survey, "S")
    for i in range(4):
        AnswerSchemaOption.objects.create(
            survey=survey, section=section, question=question, schema=schema,
            text=f"choice {i + 1}",
        )
    # bypass the signal to recreate the damaged state the migration must find
    AnswerSchemaOption.objects.filter(schema=schema, order=3).delete()
    AnswerSchemaOption.objects.filter(schema=schema, order=3).update(order=4)
    assert _orders(schema) == [1, 2, 4]

    _run()
    assert _orders(schema) == [1, 2, 3]


def test_the_surviving_choices_keep_their_identity(survey):
    section, question, schema = _schema(survey, "S")
    for i in range(4):
        AnswerSchemaOption.objects.create(
            survey=survey, section=section, question=question, schema=schema,
            text=f"choice {i + 1}",
        )
    AnswerSchemaOption.objects.filter(schema=schema, order=3).delete()
    AnswerSchemaOption.objects.filter(schema=schema, order=3).update(order=4)
    before = list(schema.options.order_by("order").values_list("text", flat=True))

    _run()
    assert list(schema.options.order_by("order").values_list("text", flat=True)) == before


def test_a_clean_schema_is_left_exactly_alone(survey):
    section, question, schema = _schema(survey, "S")
    for i in range(3):
        AnswerSchemaOption.objects.create(
            survey=survey, section=section, question=question, schema=schema,
            text=f"choice {i + 1}",
        )
    before = list(schema.options.order_by("order").values_list("id", "order", "text"))

    _run()
    assert list(schema.options.order_by("order").values_list("id", "order", "text")) == before


def test_duplicates_are_separated(survey):
    """``save`` hands a new option ``count() + 1``, so a schema that already had
    a hole gave the newcomer an order the survivor held. Both are real choices;
    the sweep must keep both and just break the tie."""
    section, question, schema = _schema(survey, "S")
    for i in range(3):
        AnswerSchemaOption.objects.create(
            survey=survey, section=section, question=question, schema=schema,
            text=f"choice {i + 1}",
        )
    AnswerSchemaOption.objects.filter(schema=schema, order=3).update(order=2)
    assert _orders(schema) == [1, 2, 2]

    _run()
    assert _orders(schema) == [1, 2, 3]
    assert schema.options.count() == 3


def test_the_sweep_is_idempotent(survey):
    section, question, schema = _schema(survey, "S")
    for i in range(4):
        AnswerSchemaOption.objects.create(
            survey=survey, section=section, question=question, schema=schema,
            text=f"choice {i + 1}",
        )
    AnswerSchemaOption.objects.filter(schema=schema, order=3).delete()
    AnswerSchemaOption.objects.filter(schema=schema, order=3).update(order=4)

    _run()
    once = list(schema.options.order_by("order").values_list("id", "order"))
    _run()
    assert list(schema.options.order_by("order").values_list("id", "order")) == once


def test_other_schemas_are_not_dragged_into_the_repair(survey):
    section_a, question_a, schema_a = _schema(survey, "A")
    for i in range(4):
        AnswerSchemaOption.objects.create(
            survey=survey, section=section_a, question=question_a, schema=schema_a,
            text=f"a{i}",
        )
    AnswerSchemaOption.objects.filter(schema=schema_a, order=3).delete()
    AnswerSchemaOption.objects.filter(schema=schema_a, order=3).update(order=4)

    section_b, question_b, schema_b = _schema(survey, "B")
    for i in range(3):
        AnswerSchemaOption.objects.create(
            survey=survey, section=section_b, question=question_b, schema=schema_b,
            text=f"b{i}",
        )
    untouched = list(schema_b.options.order_by("order").values_list("id", "order"))

    _run()
    assert _orders(schema_a) == [1, 2, 3]
    assert list(schema_b.options.order_by("order").values_list("id", "order")) == untouched
