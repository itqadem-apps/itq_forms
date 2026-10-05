"""Story survey-flow 1.2 — one renumber owner, and a survey-wide position for every question.

`renumber_questions(survey_id)` assigns `order` 1..N across the survey (`forms:AD-4`) and ranks the
sections by their first question. The save path, `reorderQuestions`, `reorderSections` and
`reorderSurveyQuestions` all reach the order through it. Until story 1.6 its key is the legacy
`(section.order nulls last, order, id)`, so a survey without sectionless questions keeps its
rendered order. `assert_forward_only` (`forms:AD-5`) is wired into every reorder and passes
trivially, since no survey carries an edge yet.

Sectionless rows are produced with `.update(section=None)`, which keeps these tests independent of
the story 1.3 author path.
"""

import pytest
from django.core.exceptions import ValidationError
from pkg_auth.authorization import AuthContext, OrgId, UserId
from strawberry import UNSET

from conftest import ORG

from surveys import question_order
from surveys.inputs import QuestionInput, QuestionPlacementInput, SectionInput
from surveys.models import AnswerSchema, AnswerSchemaOption, Question, Section
from surveys.question_order import assert_forward_only, renumber_questions
from surveys.schemas.mutations.questions import QuestionMutations
from surveys.schemas.mutations.sections import SectionMutations


def _resolver(cls, name):
    fn = getattr(cls, name)
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def _reorder_in_section(section, ids):
    return _resolver(QuestionMutations, "reorder_questions")(
        QuestionMutations(), None, section_id=str(section.id), question_ids=ids, django_user=None
    )


def _reorder_sections(survey, ids):
    return _resolver(SectionMutations, "reorder_sections")(
        SectionMutations(), None, survey_id=str(survey.id), section_ids=ids, django_user=None
    )


def _place(survey, placements):
    return _resolver(QuestionMutations, "reorder_survey_questions")(
        QuestionMutations(),
        None,
        survey_id=str(survey.id),
        placements=[
            QuestionPlacementInput(question_id=str(q), section_id=UNSET if s is UNSET else (None if s is None else str(s)))
            for q, s in placements
        ],
        django_user=None,
    )


def _rendered(survey):
    """What every reader sorts by today: `Question.Meta.ordering`, with `id` breaking ties."""
    return list(Question.objects.filter(survey=survey).order_by("section__order", "order", "id").values_list("id", flat=True))


def _orders(survey):
    return list(Question.objects.filter(survey=survey).order_by("order").values_list("id", "order"))


def _assert_contiguous(survey):
    orders = [o for _, o in _orders(survey)]
    assert orders == list(range(1, len(orders) + 1))


def _section_scoped(*sections):
    """The data every survey holds before story 1.6: `order` 1..k within each section."""
    for sec in sections:
        for i, pk in enumerate(sec.questions.order_by("order", "id").values_list("id", flat=True), start=1):
            Question.objects.filter(pk=pk).update(order=i)


@pytest.fixture
def tree(survey):
    """Sections A (two questions), B (two questions), C (one question)."""
    a = Section.objects.create(survey=survey, title="A")
    b = Section.objects.create(survey=survey, title="B")
    c = Section.objects.create(survey=survey, title="C")
    for sec in (a, b):
        Question.objects.create(survey=survey, section=sec, title=f"{sec.title}2", type="text")
    return a, b, c


def _ids(sec):
    return list(sec.questions.order_by("order", "id").values_list("id", flat=True))


# ── renumber_questions ──────────────────────────────────────────


def test_renumber_assigns_one_to_n_across_the_survey_in_the_legacy_key(survey, tree):
    a, b, c = tree
    _section_scoped(a, b, c)
    rendered = _rendered(survey)
    loose = Question.objects.create(survey=survey, section=a, title="loose", type="text")
    Question.objects.filter(pk=loose.pk).update(section=None, order=1)

    renumber_questions(survey.id)

    # The legacy key puts the sectionless question last, after every section.
    assert [pk for pk, _ in _orders(survey)] == rendered + [loose.id]
    _assert_contiguous(survey)


def test_existing_survey_keeps_its_rendered_order(survey, tree):
    a, b, c = tree
    _section_scoped(a, b, c)
    before = _rendered(survey)

    renumber_questions(survey.id)

    assert _rendered(survey) == before
    assert [pk for pk, _ in _orders(survey)] == before


def test_meta_ordering_is_unchanged_until_story_1_6():
    assert Question._meta.ordering == ["section__order", "order"]


def test_sections_are_ranked_by_their_first_question_and_empty_ones_go_last(survey, tree):
    a, b, c = tree
    empty = Section.objects.create(survey=survey, title="Empty")
    empty.questions.all().delete()
    Section.objects.filter(pk=empty.pk).update(order=2)
    Section.objects.filter(pk=b.pk).update(order=3)
    Section.objects.filter(pk=c.pk).update(order=4)

    renumber_questions(survey.id)

    ranked = list(Section.objects.filter(survey=survey).order_by("order").values_list("id", "order"))
    assert ranked == [(a.id, 1), (b.id, 2), (c.id, 3), (empty.id, 4)]


def test_a_sectionless_question_between_sections_keeps_its_place(survey, tree):
    a, b, c = tree
    renumber_questions(survey.id)
    b_ids = _ids(b)
    Question.objects.filter(pk__in=b_ids).update(section=None)
    expected = [pk for pk, _ in _orders(survey)]

    renumber_questions(survey.id)

    assert [pk for pk, _ in _orders(survey)] == expected


# ── the save path ───────────────────────────────────────────────


def test_a_created_question_lands_at_the_end_of_its_section(survey, tree):
    a, b, c = tree
    _section_scoped(a, b, c)
    before = _rendered(survey)

    added = Question.objects.create(survey=survey, section=a, title="A3", type="text")

    assert added.order == 3, "the instance is handed back its survey-wide position"
    assert [pk for pk, _ in _orders(survey)] == before[:2] + [added.id] + before[2:]
    _assert_contiguous(survey)


def test_deleting_a_question_closes_the_gap(survey, tree):
    a, b, c = tree
    Question.objects.get(pk=_ids(a)[0]).delete()
    _assert_contiguous(survey)


def test_create_and_update_ignore_a_client_order(survey, tree):
    a, b, c = tree
    created = _resolver(QuestionMutations, "create_question")(
        QuestionMutations(), None, section_id=str(b.id), input=QuestionInput(title="B3", order=1), django_user=None
    )
    assert created.order == 5
    first_of_a = _ids(a)[0]
    updated = _resolver(QuestionMutations, "update_question")(
        QuestionMutations(), None, id=str(first_of_a), input=QuestionInput(order=99), django_user=None
    )
    assert updated.order == 1
    _assert_contiguous(survey)


def test_update_section_ignores_a_client_order(survey, tree):
    a, b, c = tree
    _resolver(SectionMutations, "update_section")(
        SectionMutations(), None, id=str(c.id), input=SectionInput(order=1), django_user=None
    )
    assert list(Section.objects.filter(survey=survey).values_list("id", flat=True)) == [a.id, b.id, c.id]


# ── reorderQuestions (within a section) ─────────────────────────


def test_reorder_within_a_section_goes_through_the_renumber(survey, tree):
    a, b, c = tree
    _section_scoped(a, b, c)
    before = _rendered(survey)
    b1, b2 = _ids(b)

    result = _reorder_in_section(b, [b2, b1])

    assert [q.id for q in result] == [b2, b1]
    assert [pk for pk, _ in _orders(survey)] == before[:2] + [b2, b1] + before[4:]
    _assert_contiguous(survey)


def test_reorder_within_a_section_refuses_a_foreign_question(survey, tree):
    a, b, c = tree
    with pytest.raises(ValueError):
        _reorder_in_section(b, [_ids(a)[0]])


# ── reorderSections ─────────────────────────────────────────────


def test_reorder_sections_moves_each_sections_questions_with_it(survey, tree):
    a, b, c = tree
    _section_scoped(a, b, c)
    a_ids, b_ids, c_ids = _ids(a), _ids(b), _ids(c)

    result = _reorder_sections(survey, [c.id, a.id, b.id])

    assert [s.id for s in result] == [c.id, a.id, b.id]
    assert [pk for pk, _ in _orders(survey)] == c_ids + a_ids + b_ids
    assert _rendered(survey) == c_ids + a_ids + b_ids


def test_reorder_sections_leaves_a_sectionless_question_in_its_slot(survey, tree):
    a, b, c = tree
    renumber_questions(survey.id)
    a_ids, b_ids, c_ids = _ids(a), _ids(b), _ids(c)
    loose = b_ids[0]
    Question.objects.filter(pk=loose).update(section=None)

    _reorder_sections(survey, [c.id, b.id, a.id])

    assert [pk for pk, _ in _orders(survey)] == c_ids + [loose] + [b_ids[1]] + a_ids


def test_reorder_sections_orders_empty_sections_as_asked(survey, tree):
    a, b, c = tree
    e1 = Section.objects.create(survey=survey, title="E1")
    e2 = Section.objects.create(survey=survey, title="E2")
    Question.objects.filter(section__in=[e1, e2]).delete()

    result = _reorder_sections(survey, [e2.id, b.id, e1.id, a.id, c.id])

    assert [s.id for s in result] == [b.id, a.id, c.id, e2.id, e1.id]


# ── reorderSurveyQuestions ──────────────────────────────────────


def _layout(survey):
    return [(q.id, q.section_id) for q in Question.objects.filter(survey=survey).order_by("order")]


def test_a_move_across_a_boundary_changes_the_section(survey, tree):
    a, b, c = tree
    renumber_questions(survey.id)
    a1, a2 = _ids(a)
    b1, b2 = _ids(b)
    (c1,) = _ids(c)

    _place(survey, [(a1, a.id), (a2, a.id), (b1, a.id), (b2, b.id), (c1, c.id)])

    assert _layout(survey) == [(a1, a.id), (a2, a.id), (b1, a.id), (b2, b.id), (c1, c.id)]
    assert AnswerSchema.objects.get(question_id=b1).section_id == a.id
    assert set(AnswerSchemaOption.objects.filter(question_id=b1).values_list("section_id", flat=True)) == {a.id}
    _assert_contiguous(survey)


def test_a_layout_can_move_whole_sections_and_keeps_sectionless_questions_between_them(survey, tree):
    a, b, c = tree
    renumber_questions(survey.id)
    a1, a2 = _ids(a)
    b1, b2 = _ids(b)
    (c1,) = _ids(c)
    Question.objects.filter(pk=b1).update(section=None)

    _place(survey, [(c1, c.id), (b1, None), (a1, a.id), (a2, a.id), (b2, b.id)])

    assert _layout(survey) == [(c1, c.id), (b1, None), (a1, a.id), (a2, a.id), (b2, b.id)]
    assert list(Section.objects.filter(survey=survey).values_list("id", flat=True)) == [c.id, a.id, b.id]
    # A later save renumbers in the same order: the sectionless question stays between sections.
    Question.objects.get(pk=a1).save()
    assert _layout(survey) == [(c1, c.id), (b1, None), (a1, a.id), (a2, a.id), (b2, b.id)]


def _refused(survey, placements):
    before = _layout(survey)
    with pytest.raises(ValidationError) as excinfo:
        _place(survey, placements)
    assert set(excinfo.value.message_dict) == {"placements"}
    assert _layout(survey) == before
    return excinfo.value.message_dict["placements"]


def test_a_layout_that_splits_a_section_is_refused(survey, tree):
    a, b, c = tree
    renumber_questions(survey.id)
    a1, a2 = _ids(a)
    b1, b2 = _ids(b)
    (c1,) = _ids(c)

    messages = _refused(survey, [(a1, a.id), (b1, b.id), (a2, a.id), (b2, b.id), (c1, c.id)])
    assert any('"A"' in m for m in messages) and any('"B"' in m for m in messages)


def test_a_sectionless_question_inside_a_section_is_refused(survey, tree):
    a, b, c = tree
    renumber_questions(survey.id)
    a1, a2 = _ids(a)
    b1, b2 = _ids(b)
    (c1,) = _ids(c)
    Question.objects.filter(pk=c1).update(section=None)

    _refused(survey, [(a1, a.id), (c1, None), (a2, a.id), (b1, b.id), (b2, b.id)])


def test_a_placement_must_name_its_destination(survey, tree):
    a, b, c = tree
    a1, a2 = _ids(a)
    b1, b2 = _ids(b)
    (c1,) = _ids(c)

    _refused(survey, [(a1, a.id), (a2, UNSET), (b1, b.id), (b2, b.id), (c1, c.id)])


def test_a_layout_must_list_every_question_once(survey, tree):
    a, b, c = tree
    a1, a2 = _ids(a)
    b1, b2 = _ids(b)

    _refused(survey, [(a1, a.id), (a2, a.id), (b1, b.id), (b2, b.id)])
    _refused(survey, [(a1, a.id), (a1, a.id), (a2, a.id), (b1, b.id), (b2, b.id)])


def test_a_destination_must_be_a_section_of_the_survey(survey, tree):
    from surveys.models import Survey

    a, b, c = tree
    a1, a2 = _ids(a)
    b1, b2 = _ids(b)
    (c1,) = _ids(c)
    elsewhere = Survey.objects.create(organization_id=ORG, primary_language="en", survey_type=survey.survey_type)
    foreign = Section.objects.create(survey=elsewhere, title="F")

    _refused(survey, [(a1, foreign.id), (a2, a.id), (b1, b.id), (b2, b.id), (c1, c.id)])


def test_a_question_can_leave_its_section_and_takes_its_schema_with_it(survey, tree):
    """Story 1.3 lifted the refusal: the schema and option columns are nullable (`forms:AD-9`)."""
    a, b, c = tree
    a1, a2 = _ids(a)
    b1, b2 = _ids(b)
    (c1,) = _ids(c)

    _place(survey, [(a1, a.id), (a2, a.id), (b1, b.id), (b2, b.id), (c1, None)])

    assert Question.objects.get(pk=c1).section_id is None
    assert AnswerSchema.objects.get(question_id=c1).section_id is None
    assert not AnswerSchemaOption.objects.filter(question_id=c1, section__isnull=False).exists()


# ── assert_forward_only ─────────────────────────────────────────


def test_forward_only_passes_trivially_without_edges(survey, tree):
    assert_forward_only(survey, {pk: i for i, (pk, _) in enumerate(_orders(survey), start=1)}, field="placements")


def test_forward_only_refuses_a_backward_edge_on_the_named_field(survey, monkeypatch):
    monkeypatch.setattr(question_order, "_edges", lambda owner: [(1, 2)])
    assert_forward_only(survey, {1: 1, 2: 2}, field="placements")
    with pytest.raises(ValidationError) as excinfo:
        assert_forward_only(survey, {1: 2, 2: 1}, field="placements")
    assert set(excinfo.value.message_dict) == {"placements"}


def test_every_reorder_checks_forward_only_against_the_new_positions(survey, tree, monkeypatch):
    a, b, c = tree
    calls = []
    real = question_order.assert_forward_only

    def spy(owner, positions, field):
        calls.append((owner.pk, dict(positions), field))
        return real(owner, positions, field)

    import surveys.schemas.mutations.questions as qm
    import surveys.schemas.mutations.sections as sm

    monkeypatch.setattr(qm, "assert_forward_only", spy)
    monkeypatch.setattr(sm, "assert_forward_only", spy)
    a1, a2 = _ids(a)
    b1, b2 = _ids(b)
    (c1,) = _ids(c)

    _reorder_in_section(a, [a2, a1])
    _reorder_sections(survey, [b.id, a.id, c.id])
    _place(survey, [(c1, c.id), (a1, a.id), (a2, a.id), (b1, b.id), (b2, b.id)])

    assert [field for _, _, field in calls] == ["question_ids", "section_ids", "placements"]
    assert calls[0][1] == {a2: 1, a1: 2, b1: 3, b2: 4, c1: 5}
    assert calls[1][1] == {b1: 1, b2: 2, a2: 3, a1: 4, c1: 5}
    assert calls[2][1] == {c1: 1, a1: 2, a2: 3, b1: 4, b2: 5}


def test_a_backward_edge_refuses_the_reorder_and_writes_nothing(survey, tree, monkeypatch):
    a, b, c = tree
    a1, a2 = _ids(a)
    monkeypatch.setattr(question_order, "_edges", lambda owner: [(a1, a2)])
    before = _layout(survey)
    with pytest.raises(ValidationError) as excinfo:
        _reorder_in_section(a, [a2, a1])
    assert set(excinfo.value.message_dict) == {"question_ids"}
    assert _layout(survey) == before


# ── the client surface ──────────────────────────────────────────


class _Identity:
    def __init__(self, user):
        self.subject_str = user.id
        self.email_str = user.email
        self.preferred_username = user.username
        self.first_name = ""
        self.last_name = ""


class _Context:
    def __init__(self, user):
        self.request = None
        self.identity = _Identity(user)
        self.currency = None
        self.auth_context = AuthContext(
            user_id=UserId(user.id),
            organization_id=OrgId(ORG),
            role_names=frozenset({"org-admin"}),
            perms=frozenset({"surveys:update"}),
        )


PLACE = """
mutation Place($survey: ID!, $placements: [QuestionPlacementInput!]!) {
  reorderSurveyQuestions(surveyId: $survey, placements: $placements) {
    __typename
    ... on SurveyType { questions { id sectionId order } }
    ... on OperationInfo { messages { field kind } }
  }
}
"""


def _run(user, document, **variables):
    from surveys import schema as schema_module

    result = schema_module.schema.execute_sync(document, variable_values=variables, context_value=_Context(user))
    assert result.errors is None, result.errors
    return result.data


def test_reorder_survey_questions_over_graphql(user, survey, tree):
    a, b, c = tree
    a1, a2 = _ids(a)
    b1, b2 = _ids(b)
    (c1,) = _ids(c)

    def placements(*rows):
        return [{"questionId": str(q), "sectionId": None if s is None else str(s)} for q, s in rows]

    payload = _run(
        user, PLACE, survey=str(survey.id),
        placements=placements((b1, b.id), (b2, b.id), (a1, a.id), (a2, a.id), (c1, c.id)),
    )["reorderSurveyQuestions"]
    assert payload["__typename"] == "SurveyType", payload
    assert [(int(q["id"]), q["order"]) for q in payload["questions"]] == [(b1, 1), (b2, 2), (a1, 3), (a2, 4), (c1, 5)]

    refused = _run(
        user, PLACE, survey=str(survey.id),
        placements=placements((b1, b.id), (a1, a.id), (b2, b.id), (a2, a.id), (c1, c.id)),
    )["reorderSurveyQuestions"]
    assert refused["__typename"] == "OperationInfo", refused
    assert {m["field"] for m in refused["messages"]} == {"placements"}
    assert {m["kind"] for m in refused["messages"]} == {"VALIDATION"}


def test_a_new_question_does_not_unseat_a_sectionless_one(survey, tree):
    a, b, c = tree
    renumber_questions(survey.id)
    a1, a2 = _ids(a)
    b1, b2 = _ids(b)
    (c1,) = _ids(c)
    Question.objects.filter(pk=b1).update(section=None)
    _place(survey, [(a1, a.id), (a2, a.id), (b1, None), (b2, b.id), (c1, c.id)])

    added = Question.objects.create(survey=survey, section=a, title="A3", type="text")

    assert _layout(survey) == [(a1, a.id), (a2, a.id), (added.id, a.id), (b1, None), (b2, b.id), (c1, c.id)]
