"""Story surveys-builder 3.3: an add lands right after the card it names (`forms:AD-24`).

`insert_after` and `split_tail` are the pure placement rules; `createQuestion` and `createSection`
take an optional `after` anchor, lock the survey first and end in one `renumber_questions`
(`forms:AD-25`, `forms:AD-4`). Without `after` they still append, now under the lock.
"""

from types import SimpleNamespace

import pytest
from django.utils.timezone import now
from pkg_auth.authorization import AuthContext, OrgId, UserId

from conftest import ORG
from surveys.models import AnswerSchema, AnswerSchemaOption, Question, Section
from surveys.question_order import insert_after, renumber_questions, section_anchor, split_tail


# ── Pure rules ──────────────────────────────────────────────────

SEQ = [1, 2, 3, 4]
SECTION_OF = {1: 10, 2: 10, 3: None, 4: 20}


@pytest.mark.parametrize(
    "anchor, expected, section",
    [
        (("question", 1), [1, 9, 2, 3, 4], 10),  # Q after question
        (("section", 10), [9, 1, 2, 3, 4], 10),  # Q after heading: the section's first
        (("section", 20), [1, 2, 3, 9, 4], 20),
        (("section", 30), [1, 2, 3, 4, 9], 30),  # an empty section's only question
        (("question", 3), [1, 2, 3, 9, 4], None),  # after a loose question: sectionless
        (("survey", 7), [9, 1, 2, 3, 4], None),  # after the survey card: first, sectionless
    ],
)
def test_insert_after(anchor, expected, section):
    assert insert_after(SEQ, SECTION_OF, anchor, [9]) == (expected, section)


def test_insert_after_ignores_the_new_ids_already_in_the_sequence():
    assert insert_after(SEQ + [9], {**SECTION_OF, 9: None}, ("question", 1), [9]) == ([1, 9, 2, 3, 4], 10)


def test_split_tail():
    assert split_tail(SEQ, SECTION_OF, 1) == [2]
    assert split_tail(SEQ, SECTION_OF, 2) == []  # split at end
    assert split_tail(SEQ, SECTION_OF, 3) == []  # sectionless
    assert split_tail(SEQ, SECTION_OF, 4) == []


def test_section_anchor():
    assert section_anchor(SEQ, SECTION_OF, ("section", 10)) == ("question", 2)  # after the whole heading
    assert section_anchor(SEQ, SECTION_OF, ("section", 30)) == ("question", 4)  # empty: at the end
    assert section_anchor([], {}, ("section", 30)) == ("survey", 0)
    assert section_anchor(SEQ, SECTION_OF, ("question", 1)) == ("question", 1)
    assert section_anchor(SEQ, SECTION_OF, ("survey", 7)) == ("survey", 7)


# ── Through GraphQL ─────────────────────────────────────────────

class _Identity:
    def __init__(self, user):
        self.subject_str = user.id
        self.email_str = user.email
        self.preferred_username = user.username
        self.first_name = ""
        self.last_name = ""


class _Context:
    def __init__(self, user, org=ORG, perms=("surveys:read", "surveys:update", "surveys:create")):
        self.request = None
        self.identity = _Identity(user)
        self.currency = None
        self.auth_context = AuthContext(
            user_id=UserId(user.id),
            organization_id=OrgId(org),
            role_names=frozenset({"org-admin"}),
            perms=frozenset(perms),
        )


def run(user, document, context=None, **variables):
    from surveys import schema as schema_module

    result = schema_module.schema.execute_sync(
        document, variable_values=variables, context_value=context or _Context(user)
    )
    assert result.errors is None, result.errors
    return result.data


CREATE_QUESTION = """
mutation C($input: QuestionInput!, $after: CardAnchorInput, $sectionId: ID, $surveyId: ID) {
  createQuestion(input: $input, after: $after, sectionId: $sectionId, surveyId: $surveyId) {
    __typename
    ... on QuestionType { id order }
    ... on OperationInfo { messages { field kind message } }
  }
}
"""

CREATE_SECTION = """
mutation C($surveyId: ID!, $input: SectionInput!, $after: CardAnchorInput) {
  createSection(surveyId: $surveyId, input: $input, after: $after) {
    __typename
    ... on SectionType { id }
    ... on OperationInfo { messages { field kind message } }
  }
}
"""


def add_question(user, after=None, **kw):
    return run(user, CREATE_QUESTION, input={"title": "new", "type": "radio"}, after=after, **kw)["createQuestion"]


def add_section(user, survey, after=None):
    return run(user, CREATE_SECTION, surveyId=str(survey.id), input={"title": "S'"}, after=after)["createSection"]


def layout(survey):
    """(id, section_id) in survey order, orders checked contiguous, with schema and option sections checked alongside."""
    rows = list(Question.objects.filter(survey=survey).order_by("order").values_list("id", "order", "section_id"))
    for pk, _, section_id in rows:
        assert AnswerSchema.objects.get(question_id=pk).section_id == section_id
        assert set(AnswerSchemaOption.objects.filter(question_id=pk).values_list("section_id", flat=True)) <= {section_id}
    assert [r[1] for r in rows] == list(range(1, len(rows) + 1))
    return [(pk, section_id) for pk, _, section_id in rows]


@pytest.fixture
def tree(survey):
    """S1 holding Q1, Q2; Q3 sectionless; S2 holding Q4."""
    s1 = Section.objects.create(survey=survey, title="S1")
    s2 = Section.objects.create(survey=survey, title="S2")
    q1 = Question.objects.get(section=s1)
    q2 = Question.objects.create(survey=survey, section=s1, title="Q2")
    q3 = Question.objects.create(survey=survey, title="Q3")
    q4 = Question.objects.get(section=s2)
    renumber_questions(survey.id, [q1.id, q2.id, q3.id, q4.id])
    return SimpleNamespace(s1=s1, s2=s2, q1=q1, q2=q2, q3=q3, q4=q4)


def _new(payload):
    assert payload["__typename"] in ("QuestionType", "SectionType"), payload
    return int(payload["id"])


def test_question_after_question(user, survey, tree):
    t = tree
    new = _new(add_question(user, after={"questionId": str(t.q1.id)}))
    assert layout(survey) == [(t.q1.id, t.s1.id), (new, t.s1.id), (t.q2.id, t.s1.id), (t.q3.id, None), (t.q4.id, t.s2.id)]


def test_question_after_heading(user, survey, tree):
    t = tree
    new = _new(add_question(user, after={"sectionId": str(t.s2.id)}))
    assert layout(survey) == [(t.q1.id, t.s1.id), (t.q2.id, t.s1.id), (t.q3.id, None), (new, t.s2.id), (t.q4.id, t.s2.id)]


def test_question_after_an_empty_heading(user, survey, tree):
    t = tree
    s3 = Section.objects.create(survey=survey, title="S3")
    Question.objects.filter(section=s3).update(deleted_at=now())
    new = _new(add_question(user, after={"sectionId": str(s3.id)}))
    assert layout(survey)[-1] == (new, s3.id)
    assert list(Section.objects.filter(survey=survey).order_by("order").values_list("id", flat=True)) == [t.s1.id, t.s2.id, s3.id]


def test_question_after_loose_question(user, survey, tree):
    t = tree
    new = _new(add_question(user, after={"questionId": str(t.q3.id)}))
    assert layout(survey) == [(t.q1.id, t.s1.id), (t.q2.id, t.s1.id), (t.q3.id, None), (new, None), (t.q4.id, t.s2.id)]


def test_question_after_survey_card(user, survey, tree):
    t = tree
    payload = add_question(user, after={"surveyId": str(survey.id)})
    assert payload["order"] == 1
    assert layout(survey)[0] == (_new(payload), None)


def test_split(user, survey, tree):
    t = tree
    s_new = _new(add_section(user, survey, after={"questionId": str(t.q1.id)}))
    blank = Question.objects.get(section_id=s_new, title__isnull=True).id
    assert layout(survey) == [(t.q1.id, t.s1.id), (blank, s_new), (t.q2.id, s_new), (t.q3.id, None), (t.q4.id, t.s2.id)]
    assert list(Section.objects.filter(survey=survey).order_by("order").values_list("id", flat=True)) == [t.s1.id, s_new, t.s2.id]


def test_split_at_end(user, survey, tree):
    t = tree
    s_new = _new(add_section(user, survey, after={"questionId": str(t.q2.id)}))
    blank = Question.objects.get(section_id=s_new).id
    assert layout(survey) == [(t.q1.id, t.s1.id), (t.q2.id, t.s1.id), (blank, s_new), (t.q3.id, None), (t.q4.id, t.s2.id)]


def test_section_after_heading(user, survey, tree):
    t = tree
    s_new = _new(add_section(user, survey, after={"sectionId": str(t.s1.id)}))
    blank = Question.objects.get(section_id=s_new).id
    assert layout(survey) == [(t.q1.id, t.s1.id), (t.q2.id, t.s1.id), (blank, s_new), (t.q3.id, None), (t.q4.id, t.s2.id)]


def test_section_after_loose_question_and_survey_card(user, survey, tree):
    t = tree
    s_a = _new(add_section(user, survey, after={"questionId": str(t.q3.id)}))
    s_b = _new(add_section(user, survey, after={"surveyId": str(survey.id)}))
    a = Question.objects.get(section_id=s_a).id
    b = Question.objects.get(section_id=s_b).id
    assert layout(survey) == [
        (b, s_b), (t.q1.id, t.s1.id), (t.q2.id, t.s1.id), (t.q3.id, None), (a, s_a), (t.q4.id, t.s2.id),
    ]


def test_without_after_still_appends(user, survey, tree):
    t = tree
    new = _new(add_question(user, sectionId=str(t.s1.id)))
    s_new = _new(add_section(user, survey))
    blank = Question.objects.get(section_id=s_new).id
    assert layout(survey) == [
        (t.q1.id, t.s1.id), (t.q2.id, t.s1.id), (new, t.s1.id), (t.q3.id, None), (t.q4.id, t.s2.id), (blank, s_new),
    ]


def _refused_on_after(payload):
    assert payload["__typename"] == "OperationInfo", payload
    assert [m["field"] for m in payload["messages"]] == ["after"]


def _rows():
    return (
        sorted(Section.all_objects.values_list("id", "order", "deleted_at")),
        sorted(Question.all_objects.values_list("id", "order", "section_id", "deleted_at")),
    )


@pytest.mark.parametrize("what", ["question", "section"])
def test_stale_anchor_is_refused(user, survey, tree, what):
    t = tree
    Question.objects.filter(pk=t.q2.pk).update(deleted_at=now())
    before = _rows()
    if what == "question":
        _refused_on_after(add_question(user, after={"questionId": str(t.q2.id)}))
    else:
        _refused_on_after(add_section(user, survey, after={"questionId": str(t.q2.id)}))
    assert _rows() == before


def test_deleted_section_anchor_is_refused(user, survey, tree):
    t = tree
    Section.objects.filter(pk=t.s2.pk).update(deleted_at=now())
    before = _rows()
    _refused_on_after(add_question(user, after={"sectionId": str(t.s2.id)}))
    assert _rows() == before


def test_anchor_in_another_survey_is_refused(user, survey, tree):
    from surveys.models import Survey

    t = tree
    other = Survey.objects.create(organization_id=ORG, survey_type=survey.survey_type)
    before = _rows()
    _refused_on_after(add_section(user, other, after={"questionId": str(t.q1.id)}))
    _refused_on_after(add_question(user, after={"questionId": str(t.q1.id)}, surveyId=str(other.id)))
    _refused_on_after(add_question(user, after={"questionId": str(t.q1.id)}, sectionId=str(t.s2.id)))
    assert _rows() == before


def test_anchor_must_name_exactly_one_card(user, survey, tree):
    t = tree
    _refused_on_after(add_question(user, after={"questionId": str(t.q1.id), "sectionId": str(t.s1.id)}))
    _refused_on_after(add_question(user, after={}))


def test_an_anchor_in_another_organizations_survey_is_refused(user, survey):
    import uuid

    from surveys import schema as schema_module
    from surveys.models import Survey

    foreign = Survey.objects.create(
        organization_id=uuid.UUID("22222222-2222-2222-2222-222222222222"), survey_type=survey.survey_type
    )
    q = Question.objects.create(survey=foreign, title="Theirs")
    before = _rows()
    for document, variables in (
        (CREATE_QUESTION, {"input": {"title": "new"}, "after": {"questionId": str(q.id)}}),
        (CREATE_SECTION, {"surveyId": str(foreign.id), "input": {"title": "S'"}, "after": {"questionId": str(q.id)}}),
    ):
        result = schema_module.schema.execute_sync(document, variable_values=variables, context_value=_Context(user))
        assert result.errors and "another organization" in result.errors[0].message
    assert _rows() == before


def test_an_undecodable_anchor_id_is_refused_on_after():
    from django.core.exceptions import ValidationError

    from surveys.card_anchor import anchor_of
    from surveys.inputs import CardAnchorInput

    with pytest.raises(ValidationError) as refused:
        anchor_of(CardAnchorInput(question_id="not-an-id"))
    assert "after" in refused.value.message_dict
