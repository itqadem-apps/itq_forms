"""`duplicate_survey` produces a whole, self-contained copy (`forms:AD-3`, `forms:AD-4`).

The resolver is called with its decorators unwrapped and `ensure_in_org` stubbed, as in
`test_option_flow_edge.py`.
"""

from types import SimpleNamespace

import pytest
from django.db.models import Q

from classifications.models import Classification, ClassificationTranslation
from recommendations.models import Recommendation, RecommendationTranslation
from surveys.models import (
    AnswerSchema,
    AnswerSchemaOption,
    AnswerSchemaOptionTranslation,
    AnswerSchemaTranslation,
    FlowAction,
    Question,
    QuestionTranslation,
    Section,
    SectionTranslation,
    Survey,
    SurveyTranslation,
)
from surveys.question_order import flat_question_ids, renumber_questions
from surveys.schemas.mutations.surveys import SurveyMutations


def _resolver(cls, name):
    fn = getattr(cls, name)
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


@pytest.fixture
def duplicate(monkeypatch):
    monkeypatch.setattr("surveys.schemas.mutations.surveys.ensure_in_org", lambda *a, **k: None)
    info = SimpleNamespace(context=SimpleNamespace(auth_context=None))

    def run(survey):
        payload = _resolver(SurveyMutations, "duplicate_survey")(SurveyMutations(), info, id=survey.id, django_user=None)
        assert payload.success
        return payload.survey

    return run


def _section(survey, title):
    """A section without the blank question its post_save signal creates."""
    section = Section.objects.create(survey=survey, title=title)
    section.questions.all().delete()
    return section


def _mcq(survey, section, title, options=(("x", 1), ("y", 2))):
    question = Question.objects.create(survey=survey, section=section, title=title, type=Question.QUESTION_TYPE_RADIO_MCQ)
    schema = question.answer_schema
    schema.options.all().delete()
    for text, score in options:
        AnswerSchemaOption.objects.create(
            survey=survey, section=section, question=question, schema=schema, text=text, score=score
        )
    return question


def _questions(survey):
    return Question.objects.filter(Q(survey=survey) | Q(section__survey=survey))


def _shape(survey):
    """The survey's tree in flat order, with ids replaced by what they stand for."""
    questions = {q.pk: q for q in _questions(survey)}
    shape = []
    for pk in flat_question_ids(_questions(survey)):
        q = questions[pk]
        schema = AnswerSchema.objects.filter(question=q).first()
        options = (
            [(o.text, o.score, o.is_row, o.is_column, o.flow_action, o.flow_target.title if o.flow_target else None)
             for o in schema.options.all()]
            if schema else None
        )
        shape.append((
            q.title,
            q.section.title if q.section else None,
            q.type,
            (schema.type, schema.is_mcq, schema.is_grid, schema.with_file) if schema else None,
            options,
        ))
    return shape


def _assert_self_contained(copy, original):
    """No row of the copy references a row of the original survey."""
    sections = set(Section.objects.filter(survey=original).values_list("id", flat=True))
    questions = set(_questions(original).values_list("id", flat=True))
    schemas = set(AnswerSchema.objects.filter(question_id__in=questions).values_list("id", flat=True))
    options = set(AnswerSchemaOption.objects.filter(schema_id__in=schemas).values_list("id", flat=True))
    classifications = set(Classification.objects.filter(survey=original).values_list("id", flat=True))

    for row in Section.objects.filter(survey=copy):
        assert row.submit_action_target_id not in sections
    copy_questions = _questions(copy)
    for row in copy_questions:
        assert row.survey_id == copy.id
        assert row.section_id not in sections
    copy_schemas = AnswerSchema.objects.filter(question__in=copy_questions)
    for row in copy_schemas:
        assert row.survey_id == copy.id
        assert row.section_id not in sections
    copy_options = AnswerSchemaOption.objects.filter(schema__in=copy_schemas)
    for row in copy_options:
        assert row.survey_id == copy.id
        assert row.section_id not in sections
        assert row.question_id not in questions
        assert row.flow_target_id not in questions
        assert row.classification_id not in classifications
    for row in Recommendation.objects.filter(Q(survey=copy) | Q(option__in=copy_options)):
        assert row.option_id not in options


@pytest.fixture
def basic(survey):
    """Section A with `a1`, `a2`; section B with `b`."""
    a = _section(survey, "A")
    a1 = _mcq(survey, a, "a1", (("one", 1), ("two", 2)))
    a2 = _mcq(survey, a, "a2", (("three", 3), ("four", 4)))
    b = _section(survey, "B")
    b1 = _mcq(survey, b, "b", (("five", 5), ("six", 6)))
    return {"a": a, "b": b, "a1": a1, "a2": a2, "b1": b1}


def test_basic_copy_has_the_same_tree(survey, basic, duplicate):
    copy = duplicate(survey)

    assert Section.objects.filter(survey=copy).count() == 2
    assert _questions(copy).count() == 3
    assert AnswerSchema.objects.filter(question__in=_questions(copy)).count() == 3
    assert _shape(copy) == _shape(survey)
    _assert_self_contained(copy, survey)


def test_no_blank_question_per_cloned_section(survey, basic, duplicate):
    copy = duplicate(survey)
    assert _questions(copy).count() == _questions(survey).count()
    assert not _questions(copy).filter(title__isnull=True).exists()


def test_a_sectionless_question_keeps_its_flat_position(survey, duplicate):
    a = _section(survey, "A")
    _mcq(survey, a, "a")
    free = _mcq(survey, None, "free")
    b = _section(survey, "B")
    _mcq(survey, b, "b")
    ids = [*a.questions.values_list("id", flat=True), free.id, *b.questions.values_list("id", flat=True)]
    renumber_questions(survey.id, ids)

    copy = duplicate(survey)

    titles = [Question.objects.get(pk=pk).title for pk in flat_question_ids(_questions(copy))]
    assert titles == ["a", "free", "b"]
    assert _questions(copy).get(title="free").section_id is None
    _assert_self_contained(copy, survey)


def test_the_flat_order_maps_one_to_one(survey, basic, duplicate):
    free = _mcq(survey, None, "free")
    a, b = basic["a"], basic["b"]
    renumber_questions(survey.id, [basic["a1"].id, basic["a2"].id, free.id, basic["b1"].id])

    copy = duplicate(survey)

    original_titles = [Question.objects.get(pk=pk).title for pk in flat_question_ids(_questions(survey))]
    copy_titles = [Question.objects.get(pk=pk).title for pk in flat_question_ids(_questions(copy))]
    assert copy_titles == original_titles == ["a1", "a2", "free", "b"]
    assert list(Section.objects.filter(survey=copy).order_by("order").values_list("title", flat=True)) == [a.title, b.title]


def test_an_edge_points_at_the_copys_own_question(survey, basic, duplicate):
    option = basic["a1"].answer_schema.options.first()
    option.flow_action = FlowAction.GO_TO
    option.flow_target = basic["b1"]
    option.save()

    copy = duplicate(survey)

    edge = AnswerSchemaOption.objects.get(survey=copy, flow_action=FlowAction.GO_TO)
    assert edge.flow_target.survey_id == copy.id
    assert edge.flow_target.title == "b"
    assert edge.question.title == "a1"
    _assert_self_contained(copy, survey)


def test_seeded_options_are_replaced_by_the_originals(survey, duplicate):
    survey.use_classifications = True
    survey.create_option_for_each_classification = True
    survey.save()
    for name in ("c1", "c2", "c3"):
        c = Classification.objects.create(survey=survey, score=1)
        ClassificationTranslation.objects.create(classification=c, language="en", name=name)
    section = _section(survey, "A")
    _mcq(survey, section, "q", (("x", 1), ("y", 2)))

    copy = duplicate(survey)

    q = _questions(copy).get()
    assert list(q.answer_schema.options.order_by("order").values_list("text", "score")) == [("x", 1), ("y", 2)]
    _assert_self_contained(copy, survey)


def test_a_grid_keeps_its_rows_and_columns(survey, duplicate):
    section = _section(survey, "A")
    grid = Question.objects.create(survey=survey, section=section, title="g", type=Question.QUESTION_TYPE_RADIO_GRID)
    schema = grid.answer_schema
    schema.options.all().delete()
    for text, is_row in (("r1", True), ("r2", True), ("c1", False), ("c2", False)):
        AnswerSchemaOption.objects.create(
            survey=survey, section=section, question=grid, schema=schema, text=text, is_row=is_row, is_column=not is_row
        )

    copy = duplicate(survey)

    new_schema = _questions(copy).get().answer_schema
    assert (new_schema.type, new_schema.is_grid) == (Question.QUESTION_TYPE_RADIO_GRID, True)
    assert list(new_schema.options.order_by("order").values_list("text", "is_row", "is_column")) == [
        ("r1", True, False), ("r2", True, False), ("c1", False, True), ("c2", False, True),
    ]
    _assert_self_contained(copy, survey)


def test_an_options_classification_is_the_copys_own(survey, basic, duplicate):
    c = Classification.objects.create(survey=survey, score=3)
    ClassificationTranslation.objects.create(classification=c, language="en", name="C")
    option = basic["a1"].answer_schema.options.first()
    option.classification = c
    option.save()

    copy = duplicate(survey)

    new_c = Classification.objects.get(survey=copy)
    new_option = AnswerSchemaOption.objects.get(survey=copy, classification__isnull=False)
    assert new_option.classification_id == new_c.id
    assert new_option.text == option.text
    assert new_c.name == "C"
    _assert_self_contained(copy, survey)


def test_a_recommendation_is_on_the_copys_own_option(survey, basic, duplicate):
    option = basic["a1"].answer_schema.options.first()
    rec = Recommendation.objects.create(survey=survey, option=option)
    RecommendationTranslation.objects.create(recommendation=rec, language="en", description="do this")

    copy = duplicate(survey)

    new_rec = Recommendation.objects.get(survey=copy)
    assert new_rec.option.survey_id == copy.id
    assert new_rec.option.text == option.text
    assert new_rec.description == "do this"
    assert Recommendation.objects.get(pk=rec.pk).option_id == option.id
    _assert_self_contained(copy, survey)


def test_translations_are_copied_onto_the_copys_rows(survey, basic, duplicate):
    a1 = basic["a1"]
    SectionTranslation.objects.create(section=basic["a"], language="ar", title="أ")
    QuestionTranslation.objects.create(question=a1, language="ar", title="س")
    AnswerSchemaTranslation.objects.create(schema=a1.answer_schema, language="ar")
    option = a1.answer_schema.options.first()
    AnswerSchemaOptionTranslation.objects.create(option=option, language="ar", text="خ")

    copy = duplicate(survey)

    assert SurveyTranslation.objects.get(survey=copy, language="en").title == "Test Survey (Copy)"
    new_section = Section.objects.get(survey=copy, title="A")
    assert SectionTranslation.objects.get(section=new_section).title == "أ"
    new_a1 = _questions(copy).get(title="a1")
    assert QuestionTranslation.objects.get(question=new_a1).title == "س"
    assert AnswerSchemaTranslation.objects.get(schema=new_a1.answer_schema).language == "ar"
    new_option = new_a1.answer_schema.options.get(text=option.text)
    assert AnswerSchemaOptionTranslation.objects.get(option=new_option).text == "خ"
    # The original keeps its own, one each.
    assert SectionTranslation.objects.filter(section=basic["a"]).count() == 1
    assert AnswerSchemaTranslation.objects.filter(schema=a1.answer_schema).count() == 1


def test_an_empty_section_is_copied_with_its_translation(survey, duplicate):
    a = _section(survey, "A")
    _mcq(survey, a, "a")
    empty = _section(survey, "E")
    SectionTranslation.objects.create(section=empty, language="ar", title="فارغ")
    b = _section(survey, "B")
    _mcq(survey, b, "b")

    copy = duplicate(survey)

    assert Section.objects.filter(survey=copy).count() == Section.objects.filter(survey=survey).count() == 3
    new_empty = Section.objects.get(survey=copy, title="E")
    assert not new_empty.questions.exists()
    assert SectionTranslation.objects.get(section=new_empty).title == "فارغ"
    _assert_self_contained(copy, survey)


def test_an_option_only_recommendation_is_on_the_copys_own_option(survey, basic, duplicate):
    option = basic["a1"].answer_schema.options.order_by("order").first()
    rec = Recommendation.objects.create(survey=None, option=option)

    copy = duplicate(survey)

    new_rec = Recommendation.objects.get(option__survey=copy)
    assert new_rec.survey_id is None
    assert new_rec.option.question.title == "a1"
    assert new_rec.option.text == option.text
    assert Recommendation.objects.get(pk=rec.pk).option_id == option.id
    _assert_self_contained(copy, survey)


def test_a_submit_action_target_is_the_copys_own_section(survey, basic, duplicate):
    Section.objects.filter(pk=basic["a"].pk).update(
        submit_action=Section.SUBMIT_ACTION_JUMP, submit_action_target=basic["b"]
    )

    copy = duplicate(survey)

    new_a = Section.objects.get(survey=copy, title="A")
    assert new_a.submit_action_target.survey_id == copy.id
    assert new_a.submit_action_target.title == "B"
    _assert_self_contained(copy, survey)


def test_a_stale_schema_or_option_section_follows_the_copys_question(survey, basic, duplicate):
    a1 = basic["a1"]
    AnswerSchema.objects.filter(question=a1).update(section=basic["b"])
    AnswerSchemaOption.objects.filter(question=a1).update(section=None)

    copy = duplicate(survey)

    new_a1 = _questions(copy).get(title="a1")
    assert new_a1.section.title == "A"
    assert new_a1.answer_schema.section_id == new_a1.section_id
    assert set(new_a1.answer_schema.options.values_list("section_id", flat=True)) == {new_a1.section_id}
    _assert_self_contained(copy, survey)


def _rows(survey):
    questions = _questions(survey)
    return (
        list(Survey.objects.filter(pk=survey.pk).values()),
        list(Section.objects.filter(survey=survey).order_by("id").values()),
        list(questions.order_by("id").values()),
        list(AnswerSchema.objects.filter(question__in=questions).order_by("id").values()),
        list(AnswerSchemaOption.objects.filter(question__in=questions).order_by("id").values()),
        list(Classification.objects.filter(survey=survey).order_by("id").values()),
        list(Recommendation.objects.filter(Q(survey=survey) | Q(option__survey=survey)).order_by("id").values()),
    )


def test_the_original_is_untouched(survey, basic, duplicate):
    c = Classification.objects.create(survey=survey, score=3)
    option = basic["a1"].answer_schema.options.first()
    option.classification = c
    option.flow_action = FlowAction.GO_TO
    option.flow_target = basic["b1"]
    option.save()
    Recommendation.objects.create(survey=survey, option=option)
    before = _rows(survey)

    copy = duplicate(survey)

    assert _rows(survey) == before
    _assert_self_contained(copy, survey)
    # Deleting the original leaves the copy whole: nothing in it cascades from the original.
    shape = _shape(copy)
    Survey.objects.get(pk=survey.pk).delete()
    assert _shape(copy) == shape
    assert Recommendation.objects.filter(survey=copy).count() == 1
