"""Story surveys-builder 3.3: one `copy_question` serves Duplicate and Import (`forms:AD-24`).

The copy is independent and takes the question, its schema, its live options and every
translation of the three; every edge falls through. Duplicate keeps everything inside its own
survey and lands right after the original. Import lands right after the card it names and, across
surveys, clears classification, ending option and images while keeping score. Import needs read
on the source survey and update on the target, both in the caller's organization.
"""

import uuid
from types import SimpleNamespace

import pytest
from django.utils.timezone import now

from classifications.models import Classification
from conftest import ORG
from surveys.models import (
    AnswerSchemaOption,
    AnswerSchemaOptionTranslation,
    AnswerSchemaTranslation,
    FlowAction,
    Question,
    QuestionTranslation,
    Section,
    Survey,
)
from surveys.question_order import renumber_questions
from tests.test_insert_after import _Context, layout, run

OTHER_ORG = uuid.UUID("22222222-2222-2222-2222-222222222222")


def _survey(org=ORG):
    return Survey.objects.create(organization_id=org, survey_type=Survey.ASSESSMENT_TYPE_SURVEY, primary_language="en")


@pytest.fixture
def source(survey):
    """Survey A: S1 holding Q1 (rich, routed) and Q2; Q1's third option soft-deleted."""
    s1 = Section.objects.create(survey=survey, title="S1")
    q1 = Question.objects.get(section=s1)
    q2 = Question.objects.create(survey=survey, section=s1, title="Q2")
    renumber_questions(survey.id, [q1.id, q2.id])
    Question.objects.filter(pk=q1.pk).update(title="Colour", cover_asset_id="cover-1")
    q1.refresh_from_db()
    QuestionTranslation.objects.create(question=q1, language="ar", title="لون", description="d")
    AnswerSchemaTranslation.objects.create(schema=q1.answer_schema, language="ar")
    classification = Classification.objects.create(survey=survey, score=5)
    schema = q1.answer_schema
    schema.options.all().delete()
    red = AnswerSchemaOption.objects.create(
        survey=survey, section=s1, question=q1, schema=schema, text="Red", score=10,
        classification=classification, ending_option=True, image_asset_id="img-red",
        flow_action=FlowAction.GO_TO, flow_target=q2,
    )
    blue = AnswerSchemaOption.objects.create(
        survey=survey, section=s1, question=q1, schema=schema, text="Blue", score=20, flow_action=FlowAction.TERMINATE,
    )
    gone = AnswerSchemaOption.objects.create(survey=survey, section=s1, question=q1, schema=schema, text="Gone")
    AnswerSchemaOption.objects.filter(pk=gone.pk).update(deleted_at=now())
    AnswerSchemaOptionTranslation.objects.create(option=red, language="ar", text="أحمر")
    return SimpleNamespace(survey=survey, s1=s1, q1=q1, q2=q2, classification=classification)


def _options(question):
    return list(
        AnswerSchemaOption.all_objects.filter(question=question).order_by("order").values_list(
            "text", "score", "classification_id", "ending_option", "image_asset_id", "flow_action", "flow_target_id",
            "deleted_at", "section_id",
        )
    )


def _snapshot(question):
    return (
        Question.all_objects.filter(pk=question.pk).values_list("title", "order", "section_id", "cover_asset_id").get(),
        _options(question),
        list(QuestionTranslation.objects.filter(question=question).values_list("language", "title")),
    )


DUPLICATE = """
mutation D($id: ID!) {
  duplicateQuestion(id: $id) {
    __typename
    ... on QuestionType { id order }
    ... on OperationInfo { messages { field kind message } }
  }
}
"""

IMPORT = """
mutation I($source: ID!, $after: CardAnchorInput!) {
  importQuestion(sourceQuestionId: $source, after: $after) {
    __typename
    ... on QuestionType { id order }
    ... on OperationInfo { messages { field kind message } }
  }
}
"""


def _import(user, source_q, after, context=None):
    return run(user, IMPORT, context=context, source=str(source_q.id), after=after)["importQuestion"]


def _import_raw(user, source_q, after, context):
    from surveys import schema as schema_module

    return schema_module.schema.execute_sync(
        IMPORT, variable_values={"source": str(source_q.id), "after": after}, context_value=context
    )


# ── Duplicate ───────────────────────────────────────────────────

def test_duplicate_keeps_everything_inside_its_survey(user, source):
    s = source
    payload = run(user, DUPLICATE, id=str(s.q1.id))["duplicateQuestion"]
    copy = Question.objects.get(pk=int(payload["id"]))

    assert layout(s.survey) == [(s.q1.id, s.s1.id), (copy.id, s.s1.id), (s.q2.id, s.s1.id)]
    assert copy.title == "Colour (Copy)"
    assert copy.cover_asset_id == "cover-1"
    assert list(QuestionTranslation.objects.filter(question=copy).values_list("language", "title", "description")) == [
        ("ar", "لون (Copy)", "d"),
    ]
    assert list(AnswerSchemaTranslation.objects.filter(schema=copy.answer_schema).values_list("language", flat=True)) == ["ar"]
    assert _options(copy) == [
        ("Red", 10, s.classification.id, True, "img-red", FlowAction.FALL_THROUGH, None, None, s.s1.id),
        ("Blue", 20, None, None, None, FlowAction.FALL_THROUGH, None, None, s.s1.id),
    ]
    red_copy = AnswerSchemaOption.objects.get(question=copy, text="Red")
    assert list(red_copy.translations.values_list("language", "text")) == [("ar", "أحمر")]


def test_duplicate_of_a_loose_question_stays_loose(user, survey):
    q = Question.objects.create(survey=survey, title="Loose")
    s = Section.objects.create(survey=survey, title="S")
    payload = run(user, DUPLICATE, id=str(q.id))["duplicateQuestion"]
    assert layout(survey) == [(q.id, None), (int(payload["id"]), None), (Question.objects.get(section=s).id, s.id)]


# ── Import ──────────────────────────────────────────────────────

@pytest.fixture
def target():
    """Survey B: Q1, Q2 sectionless; S holding Q3."""
    b = _survey()
    q1 = Question.objects.create(survey=b, title="B1")
    q2 = Question.objects.create(survey=b, title="B2")
    s = Section.objects.create(survey=b, title="BS")
    q3 = Question.objects.get(section=s)
    renumber_questions(b.id, [q1.id, q2.id, q3.id])
    return SimpleNamespace(survey=b, q1=q1, q2=q2, s=s, q3=q3)


def test_import_is_an_independent_copy_after_the_card(user, source, target):
    s, t = source, target
    before = _snapshot(s.q1)
    payload = _import(user, s.q1, {"questionId": str(t.q2.id)})
    copy = Question.objects.get(pk=int(payload["id"]))

    assert layout(t.survey) == [(t.q1.id, None), (t.q2.id, None), (copy.id, None), (t.q3.id, t.s.id)]
    assert copy.survey_id == t.survey.id
    assert copy.title == "Colour"
    assert copy.cover_asset_id is None
    assert list(QuestionTranslation.objects.filter(question=copy).values_list("language", "title")) == [("ar", "لون")]
    assert list(AnswerSchemaTranslation.objects.filter(schema=copy.answer_schema).values_list("language", flat=True)) == ["ar"]
    assert _options(copy) == [
        ("Red", 10, None, None, None, FlowAction.FALL_THROUGH, None, None, None),
        ("Blue", 20, None, None, None, FlowAction.FALL_THROUGH, None, None, None),
    ]
    assert set(AnswerSchemaOption.objects.filter(question=copy).values_list("survey_id", flat=True)) == {t.survey.id}

    # Editing the copy never reaches the source.
    Question.objects.filter(pk=copy.pk).update(title="Edited")
    AnswerSchemaOption.objects.filter(question=copy).update(text="Edited")
    assert _snapshot(s.q1) == before


def test_import_into_a_section_heading(user, source, target):
    s, t = source, target
    payload = _import(user, s.q2, {"sectionId": str(t.s.id)})
    assert layout(t.survey)[2] == (int(payload["id"]), t.s.id)


def test_import_within_the_same_survey_keeps_classification(user, source):
    s = source
    payload = _import(user, s.q1, {"surveyId": str(s.survey.id)})
    copy = Question.objects.get(pk=int(payload["id"]))
    assert payload["order"] == 1
    assert copy.title == "Colour"
    assert _options(copy)[0][:5] == ("Red", 10, s.classification.id, True, "img-red")


def _all_rows():
    return (
        sorted(Question.all_objects.values_list("id", "order", "section_id")),
        AnswerSchemaOption.all_objects.count(),
    )


def test_import_without_read_on_the_source_is_refused(user, source, target):
    before = _all_rows()
    result = _import_raw(user, source.q1, {"questionId": str(target.q1.id)}, _Context(user, perms=("surveys:update",)))
    assert result.errors and "surveys:read" in result.errors[0].message
    assert _all_rows() == before


def test_import_from_another_organization_is_refused(user, target):
    foreign = _survey(OTHER_ORG)
    q = Question.objects.create(survey=foreign, title="Theirs")
    before = _all_rows()
    result = _import_raw(user, q, {"questionId": str(target.q1.id)}, _Context(user))
    assert result.errors and "another organization" in result.errors[0].message
    assert _all_rows() == before


def test_import_into_another_organization_is_refused(user, source):
    foreign = _survey(OTHER_ORG)
    q = Question.objects.create(survey=foreign, title="Theirs")
    before = _all_rows()
    result = _import_raw(user, source.q1, {"questionId": str(q.id)}, _Context(user))
    assert result.errors and "another organization" in result.errors[0].message
    assert _all_rows() == before


@pytest.mark.parametrize("gone", ["question", "section", "survey"])
def test_import_of_a_deleted_source_is_refused(user, source, target, gone):
    s = source
    if gone == "question":
        Question.objects.filter(pk=s.q1.pk).update(deleted_at=now())
    elif gone == "section":
        Section.objects.filter(pk=s.s1.pk).update(deleted_at=now())
    else:
        Survey.objects.filter(pk=s.survey.pk).update(deleted_at=now())
    before = _all_rows()
    payload = _import(user, s.q1, {"questionId": str(target.q1.id)})
    assert payload["__typename"] == "OperationInfo", payload
    assert [m["field"] for m in payload["messages"]] == ["sourceQuestionId"]
    assert _all_rows() == before


def test_import_after_a_stale_anchor_is_refused(user, source, target):
    Question.objects.filter(pk=target.q2.pk).update(deleted_at=now())
    before = _all_rows()
    payload = _import(user, source.q1, {"questionId": str(target.q2.id)})
    assert payload["__typename"] == "OperationInfo", payload
    assert [m["field"] for m in payload["messages"]] == ["after"]
    assert _all_rows() == before


def test_import_without_update_on_the_target_is_refused(user, source, target):
    before = _all_rows()
    result = _import_raw(user, source.q1, {"questionId": str(target.q1.id)}, _Context(user, perms=("surveys:read",)))
    assert result.errors and "surveys:update" in result.errors[0].message
    assert _all_rows() == before


def test_import_needs_read_on_the_source_kind(user, target):
    exam = Survey.objects.create(organization_id=ORG, survey_type=Survey.ASSESSMENT_TYPE_EXAM, primary_language="en")
    q = Question.objects.create(survey=exam, title="Exam Q")
    before = _all_rows()
    result = _import_raw(user, q, {"questionId": str(target.q1.id)}, _Context(user))
    assert result.errors and "exams:read" in result.errors[0].message
    assert _all_rows() == before


def test_a_deleted_foreign_source_reads_like_a_live_one(user, target):
    foreign = _survey(OTHER_ORG)
    q = Question.objects.create(survey=foreign, title="Theirs")
    Question.objects.filter(pk=q.pk).update(deleted_at=now())
    before = _all_rows()
    result = _import_raw(user, q, {"questionId": str(target.q1.id)}, _Context(user))
    assert result.errors and "another organization" in result.errors[0].message
    assert _all_rows() == before


def _orphan(target):
    """A legacy row with neither survey nor section (the schema signal needs a survey to create)."""
    q = Question.objects.create(survey=target.survey, title="Orphan")
    Question.all_objects.filter(pk=q.pk).update(survey=None, section=None, order=None)
    q.refresh_from_db()
    return q


def test_a_source_with_no_survey_is_refused(user, target):
    q = _orphan(target)
    before = _all_rows()
    payload = _import(user, q, {"questionId": str(target.q1.id)})
    assert payload["__typename"] == "OperationInfo", payload
    assert [m["field"] for m in payload["messages"]] == ["sourceQuestionId"]
    assert _all_rows() == before


def test_copy_question_refuses_a_source_with_no_survey(target):
    from django.core.exceptions import ValidationError

    from surveys.question_copy import copy_question

    q = _orphan(target)
    with pytest.raises(ValidationError) as refused:
        copy_question(q, target.survey, None, as_duplicate=True)
    assert set(refused.value.message_dict) == {"id"}


def test_duplicate_of_a_deleted_question_is_refused(user, source):
    Question.objects.filter(pk=source.q2.pk).update(deleted_at=now())
    before = _all_rows()
    payload = run(user, DUPLICATE, id=str(source.q2.id))["duplicateQuestion"]
    assert payload["__typename"] == "OperationInfo", payload
    assert [m["field"] for m in payload["messages"]] == ["id"]
    assert _all_rows() == before


def test_duplicate_title_fits_the_column(user, survey):
    q = Question.objects.create(survey=survey, title="x" * 255)
    QuestionTranslation.objects.create(question=q, language="ar", title="y" * 255)
    copy = Question.objects.get(pk=int(run(user, DUPLICATE, id=str(q.id))["duplicateQuestion"]["id"]))
    assert copy.title == "x" * 248 + " (Copy)"
    assert QuestionTranslation.objects.get(question=copy).title == "y" * 248 + " (Copy)"
