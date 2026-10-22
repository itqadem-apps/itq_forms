"""Story surveys-builder 3.2: flatten dissolves an untitled section in place (`forms:AD-23`).

Its questions become sectionless through `move_to_section` — question, schema and option sections
together — and keep their survey-wide order; the section is soft-deleted (`forms:AD-21`). A
section with a title in any language is refused on `title`. The untitled check runs after the
survey lock (`forms:AD-25`), and section-title writes take the same lock.
"""

import pytest

from media import grants as media_access
from surveys.models import AnswerSchema, AnswerSchemaOption, Question, Section, SectionTranslation
from surveys.question_order import renumber_questions
from tests.test_soft_delete import detail, mutate, run, state


@pytest.fixture
def layout(survey):
    """Q0 sectionless; S1 (untitled) holding Q1, Q2; S2 holding Q3."""
    q0 = Question.objects.create(survey=survey, title="Q0")
    s1 = Section.objects.create(survey=survey, title="")
    s2 = Section.objects.create(survey=survey, title="S2")
    q1 = Question.objects.get(section=s1)
    q2 = Question.objects.create(survey=survey, section=s1, title="Q2")
    q3 = Question.objects.get(section=s2)
    renumber_questions(survey.id, [q0.id, q1.id, q2.id, q3.id])
    return q0, s1, s2, q1, q2, q3


def test_flatten_an_untitled_section(user, survey, layout):
    q0, s1, s2, q1, q2, q3 = layout
    Question.all_objects.filter(pk=q2.pk).update(cover_asset_id="asset-q2")
    SectionTranslation.objects.create(section=s1, language="ar", title="  ", description="")

    assert mutate(user, "flattenSection", s1.id)["__typename"] == "OperationResult"

    assert list(Question.objects.filter(survey=survey).order_by("order").values_list("id", "order", "section_id")) == [
        (q0.id, 1, None), (q1.id, 2, None), (q2.id, 3, None), (q3.id, 4, s2.id),
    ]
    assert set(AnswerSchema.objects.filter(question__in=[q1, q2]).values_list("section_id", flat=True)) == {None}
    assert set(AnswerSchemaOption.objects.filter(question__in=[q1, q2]).values_list("section_id", flat=True)) == {None}
    assert Section.all_objects.get(pk=s1.pk).deleted_at is not None
    assert not Question.all_objects.filter(pk__in=[q1.pk, q2.pk], deleted_at__isnull=False).exists()
    assert "asset-q2" in media_access._collect_restricted_asset_ids(survey.id)

    payload = detail(user, survey)
    assert [int(s["id"]) for s in payload["sections"]] == [s2.id]
    assert [(int(q["id"]), q["sectionId"] and int(q["sectionId"])) for q in payload["questions"]] == [
        (q0.id, None), (q1.id, None), (q2.id, None), (q3.id, s2.id),
    ]


@pytest.mark.parametrize("titled", ["legacy", "translation"])
def test_flatten_a_titled_section_is_refused(user, survey, layout, titled):
    q0, s1, *_ = layout
    if titled == "legacy":
        Section.all_objects.filter(pk=s1.pk).update(title="Kept")
    else:
        SectionTranslation.objects.create(section=s1, language="ar", title="عنوان")
    before = state()

    refused = mutate(user, "flattenSection", s1.id)

    assert refused["__typename"] == "OperationInfo", refused
    assert [(m["field"], m["kind"]) for m in refused["messages"]] == [("title", "VALIDATION")]
    assert state() == before


def test_media_access_reads_questions_by_survey(survey, layout):
    q0, *_ = layout
    Question.all_objects.filter(pk=q0.pk).update(cover_asset_id="asset-q0")

    assert "asset-q0" in media_access._collect_restricted_asset_ids(survey.id)


def test_media_access_keeps_legacy_and_deleted_rows(user, survey, layout):
    """A legacy question with no `survey_id` belongs through its section; a soft-deleted
    section, question or option keeps its asset, which existing snapshots still show."""
    q0, s1, s2, q1, q2, q3 = layout
    Question.all_objects.filter(pk=q3.pk).update(survey=None, cover_asset_id="asset-legacy")
    Section.all_objects.filter(pk=s1.pk).update(cover_asset_id="asset-s1")
    Question.all_objects.filter(pk=q1.pk).update(cover_asset_id="asset-q1")
    option = AnswerSchemaOption.all_objects.filter(question=q1).first()
    AnswerSchemaOption.all_objects.filter(pk=option.pk).update(image_asset_id="asset-o1")

    assert mutate(user, "deleteSection", s1.id)["__typename"] == "OperationResult"

    assert {"asset-legacy", "asset-s1", "asset-q1", "asset-o1"} <= set(media_access._collect_restricted_asset_ids(survey.id))


def test_flatten_gives_a_legacy_question_its_sections_survey(user, survey, layout):
    q0, s1, s2, q1, q2, q3 = layout
    Question.all_objects.filter(pk=q2.pk).update(survey=None)

    assert mutate(user, "flattenSection", s1.id)["__typename"] == "OperationResult"

    assert Question.objects.values_list("survey_id", "section_id").get(pk=q2.pk) == (survey.id, None)
    assert [q["id"] for q in detail(user, survey)["questions"]].count(str(q2.id)) == 1


def test_flatten_and_section_title_writes_lock_the_survey_first(user, survey, layout, monkeypatch):
    from django.db.models.query import QuerySet

    from surveys.models import Survey

    q0, s1, s2, *_ = layout
    calls = []
    real_lock = QuerySet.select_for_update

    def lock(self, *a, **k):
        calls.append(self.model)
        return real_lock(self, *a, **k)

    monkeypatch.setattr(QuerySet, "select_for_update", lock)

    created = run(user, """
    mutation C($id: ID!) {
      createSectionTranslation(sectionId: $id, input: {language: "fr", title: ""}) {
        __typename ... on SectionTranslationType { id }
      }
    }""", id=str(s1.id))["createSectionTranslation"]
    assert created["__typename"] == "SectionTranslationType", created
    assert calls == [Survey]

    calls.clear()
    assert mutate(user, "flattenSection", s1.id)["__typename"] == "OperationResult"
    assert calls == [Survey]

    calls.clear()
    updated = run(user, """
    mutation U($id: ID!) {
      updateSection(id: $id, input: {description: "d"}) { __typename }
    }""", id=str(s2.id))["updateSection"]
    assert updated["__typename"] == "SectionType", updated
    assert calls == [Survey]

    translation = SectionTranslation.objects.create(section=s2, language="ar", title="ع")
    calls.clear()
    renamed = run(user, """
    mutation T($id: UUID!) {
      updateSectionTranslation(id: $id, input: {language: "ar", title: "عنوان"}) {
        __typename ... on SectionTranslationType { id }
      }
    }""", id=str(translation.pk))["updateSectionTranslation"]
    assert renamed["__typename"] == "SectionTranslationType", renamed
    assert calls == [Survey]

    calls.clear()
    removed = run(user, """
    mutation X($id: UUID!) {
      deleteSectionTranslation(id: $id) { __typename }
    }""", id=str(translation.pk))["deleteSectionTranslation"]
    assert removed["__typename"] == "OperationResult", removed
    assert calls == [Survey]
