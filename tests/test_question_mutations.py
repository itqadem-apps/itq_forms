"""Regression cover for QuestionMutations.

`duplicate_question` shipped broken: it created a second AnswerSchema for a
question that the post_save signal had already given one, and AnswerSchema.question
is a OneToOneField. There was no test, so nothing caught it.

These call the resolver body directly. The strawberry/permission decorators are
unwrapped away, so what is under test is the data manipulation, not the GraphQL
surface or the permission check.
"""

import pytest

from surveys.models import AnswerSchema, AnswerSchemaOption, Question, QuestionTranslation
from surveys.schemas.mutations.questions import QuestionMutations


def _resolver(name):
    fn = getattr(QuestionMutations, name)
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def _duplicate(question):
    return _resolver("duplicate_question")(QuestionMutations(), None, id=question.id, django_user=None)


def test_duplicate_question_leaves_exactly_one_schema(question):
    """The bug: a second AnswerSchema for one question. Postgres refused it outright."""
    new_question = _duplicate(question)

    assert new_question.pk != question.pk
    assert AnswerSchema.objects.filter(question=new_question).count() == 1


def test_duplicate_question_copies_schema_shape(question):
    schema = question.answer_schema
    schema.is_mcq = True
    schema.with_file = True
    schema.save()

    new_schema = _duplicate(question).answer_schema

    assert (new_schema.type, new_schema.is_mcq, new_schema.is_grid, new_schema.with_file) == (
        schema.type, schema.is_mcq, schema.is_grid, schema.with_file,
    )


def test_duplicate_question_copies_options_and_drops_the_seeded_one(question):
    """The copy takes the original's options -- not those, plus the signal's blank."""
    question.answer_schema.options.all().delete()
    for text in ("Red", "Green", "Blue"):
        question.answer_schema.options.create(
            survey=question.survey, section=question.section, question=question, text=text,
        )

    new_question = _duplicate(question)
    options = list(new_question.answer_schema.options.all())

    assert [o.text for o in options] == ["Red", "Green", "Blue"]
    assert AnswerSchemaOption.objects.filter(question=new_question).count() == 3


def test_duplicate_question_marks_the_copy(question):
    question.title = "What is your favorite color?"
    question.save()

    assert _duplicate(question).title == "What is your favorite color? (Copy)"


def test_duplicate_question_copies_translations(question):
    QuestionTranslation.objects.create(
        question=question, language="ar", title="سؤال", description="وصف",
    )

    new_question = _duplicate(question)
    translation = QuestionTranslation.objects.get(question=new_question, language="ar")

    assert translation.title == "سؤال (Copy)"
    assert translation.description == "وصف"
