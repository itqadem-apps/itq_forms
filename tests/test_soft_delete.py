"""Story surveys-builder 3.2: builder deletes are soft, and a live jump target cannot be deleted.

`forms:AD-21`: a section, question or option delete stamps its group with one `deleted_at`; the
default managers, every related manager and the GraphQL optimizer stop returning it, while
`all_objects` still does. `forms:AD-22`: a section or question is refused on `target_id` while a
live option outside the deleted set jumps into it. `forms:AD-25`: each delete locks the survey
first.
"""

from types import SimpleNamespace

import pytest
from pkg_auth.authorization import AuthContext, OrgId, UserId

from conftest import ORG
from surveys.models import AnswerSchema, AnswerSchemaOption, FlowAction, Question, Section
from surveys.question_order import renumber_questions
from surveys.schemas.mutations.surveys import SurveyMutations
from user_surveys.models import UserAnswerOption, UserQuestion, UserSection
from user_surveys.services import enroll_user_in_assessment


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
            perms=frozenset({"surveys:read", "surveys:update", "surveys:create"}),
        )


def run(user, document, **variables):
    from surveys import schema as schema_module

    result = schema_module.schema.execute_sync(document, variable_values=variables, context_value=_Context(user))
    assert result.errors is None, result.errors
    return result.data


def mutate(user, name, id):
    document = f"""
    mutation M($id: ID!) {{
      {name}(id: $id) {{
        __typename
        ... on OperationResult {{ success }}
        ... on OperationInfo {{ messages {{ field kind message }} }}
      }}
    }}
    """
    return run(user, document, id=str(id))[name]


DETAIL = """
query D($id: ID!) {
  survey(id: $id) {
    sections { id questions { id order answerSchema { options { id order } } } }
    questions { id order sectionId answerSchema { options { id order } } }
  }
}
"""


def detail(user, survey):
    return run(user, DETAIL, id=str(survey.id))["survey"]


def state():
    """Every row, deleted or not, as the support manager sees it."""
    return (
        sorted(Section.all_objects.values_list("id", "deleted_at", "order", "submit_action_target_id")),
        sorted(Question.all_objects.values_list("id", "deleted_at", "order", "section_id")),
        sorted(AnswerSchemaOption.all_objects.values_list("id", "deleted_at", "order", "flow_action", "flow_target_id")),
    )


def options_of(question):
    return list(AnswerSchemaOption.all_objects.filter(question=question).order_by("order", "id"))


def set_text(question, *texts):
    """Give `question` exactly these option texts, in order."""
    opts = options_of(question)
    for opt, text in zip(opts, texts):
        AnswerSchemaOption.all_objects.filter(pk=opt.pk).update(text=text)
    for text in texts[len(opts):]:
        AnswerSchemaOption.objects.create(
            survey_id=question.survey_id, section_id=question.section_id, question=question,
            schema=question.answer_schema, text=text,
        )
    return options_of(question)


def jump(option, target):
    AnswerSchemaOption.all_objects.filter(pk=option.pk).update(flow_action=FlowAction.GO_TO, flow_target=target)


@pytest.fixture
def tree(survey):
    """S1 holding Q1, Q2; S2 holding Q3, Q4; survey-wide 1..4."""
    s1 = Section.objects.create(survey=survey, title="S1")
    s2 = Section.objects.create(survey=survey, title="S2")
    q1 = Question.objects.get(section=s1)
    q2 = Question.objects.create(survey=survey, section=s1, title="Q2")
    q3 = Question.objects.get(section=s2)
    q4 = Question.objects.create(survey=survey, section=s2, title="Q4")
    renumber_questions(survey.id, [q1.id, q2.id, q3.id, q4.id])
    return s1, s2, q1, q2, q3, q4


def test_section_delete_stamps_one_group_and_renumbers(user, survey, tree):
    s1, s2, q1, q2, q3, q4 = tree

    assert mutate(user, "deleteSection", s1.id)["__typename"] == "OperationResult"

    stamps = {
        Section.all_objects.get(pk=s1.pk).deleted_at,
        *Question.all_objects.filter(pk__in=[q1.pk, q2.pk]).values_list("deleted_at", flat=True),
        *AnswerSchemaOption.all_objects.filter(question__in=[q1, q2]).values_list("deleted_at", flat=True),
    }
    assert len(stamps) == 1 and None not in stamps
    assert Section.all_objects.filter(pk=s1.pk).exists()
    assert not Section.objects.filter(pk=s1.pk).exists()
    assert not Question.objects.filter(pk__in=[q1.pk, q2.pk]).exists()
    assert not AnswerSchema.objects.filter(question__in=[q1, q2]).exists()
    assert AnswerSchema.all_objects.filter(question__in=[q1, q2]).count() == 2
    assert list(Question.objects.filter(survey=survey).order_by("order").values_list("id", "order")) == [(q3.id, 1), (q4.id, 2)]
    assert Section.objects.get(pk=s2.pk).order == 1
    assert list(survey.sections.all()) == [s2]
    assert list(s1.questions.all()) == []

    payload = detail(user, survey)
    assert [int(s["id"]) for s in payload["sections"]] == [s2.id]
    assert [(int(q["id"]), q["order"]) for q in payload["questions"]] == [(q3.id, 1), (q4.id, 2)]


def test_a_live_jump_target_is_refused_and_nothing_changes(user, survey, tree):
    s1, s2, q1, q2, q3, q4 = tree
    yes, = set_text(q1, "Yes")
    jump(yes, q3)
    before = state()

    for name, target in (("deleteQuestion", q3.id), ("deleteSection", s2.id)):
        refused = mutate(user, name, target)
        assert refused["__typename"] == "OperationInfo", refused
        assert [(m["field"], m["kind"], m["message"]) for m in refused["messages"]] == [
            ("targetId", "VALIDATION", "Question 1 — Yes")
        ]
        assert state() == before

    # Re-pointed first, the delete goes through.
    AnswerSchemaOption.all_objects.filter(pk=yes.pk).update(flow_action=FlowAction.FALL_THROUGH, flow_target=None)
    assert mutate(user, "deleteQuestion", q3.id)["__typename"] == "OperationResult"


def test_the_refusal_names_every_referrer_by_position_and_translation(user, survey, tree):
    from surveys.models import AnswerSchemaOptionTranslation

    s1, s2, q1, q2, q3, q4 = tree
    a, = set_text(q1, "")
    AnswerSchemaOptionTranslation.objects.create(option=a, language="en", text="Maybe")
    b, = set_text(q2, "No")
    jump(a, q4)
    jump(b, q4)

    refused = mutate(user, "deleteQuestion", q4.id)
    assert [m["message"] for m in refused["messages"]] == ["Question 1 — Maybe", "Question 2 — No"]


def test_an_edge_inside_the_deleted_set_does_not_block(user, survey, tree):
    s1, s2, q1, q2, q3, q4 = tree
    opt, = options_of(q3)
    jump(opt, q4)

    assert mutate(user, "deleteSection", s2.id)["__typename"] == "OperationResult"
    assert AnswerSchemaOption.all_objects.get(pk=opt.pk).deleted_at is not None


def test_a_deleted_referrer_does_not_block(user, survey, tree):
    s1, s2, q1, q2, q3, q4 = tree
    opt, = options_of(q1)
    jump(opt, q3)
    assert mutate(user, "deleteAnswerSchemaOption", opt.id)["__typename"] == "OperationResult"

    assert mutate(user, "deleteQuestion", q3.id)["__typename"] == "OperationResult"


def test_option_delete_is_soft_resequences_and_never_blocks(user, survey, tree):
    s1, s2, q1, q2, q3, q4 = tree
    a, b, c = set_text(q1, "A", "B", "C")
    jump(b, q4)

    assert mutate(user, "deleteAnswerSchemaOption", b.id)["__typename"] == "OperationResult"

    deleted = AnswerSchemaOption.all_objects.get(pk=b.pk)
    assert deleted.deleted_at is not None and deleted.order == 2
    assert list(q1.answer_schema.options.values_list("id", "order")) == [(a.id, 1), (c.id, 2)]
    payload = detail(user, survey)
    q1_payload = next(q for q in payload["questions"] if int(q["id"]) == q1.id)
    assert [int(o["id"]) for o in q1_payload["answerSchema"]["options"]] == [a.id, c.id]
    # The next option counts live options only.
    new = AnswerSchemaOption.objects.create(survey=survey, section=s1, question=q1, schema=q1.answer_schema, text="D")
    assert new.order == 3


def test_a_legacy_section_target_does_not_block_and_is_nulled(user, survey, tree):
    s1, s2, *_ = tree
    Section.all_objects.filter(pk=s1.pk).update(submit_action=Section.SUBMIT_ACTION_JUMP, submit_action_target=s2)

    assert mutate(user, "deleteSection", s2.id)["__typename"] == "OperationResult"
    assert Section.all_objects.get(pk=s1.pk).submit_action_target_id is None


def test_the_optimizer_does_not_fetch_deleted_rows(user, survey, tree):
    s1, s2, q1, q2, q3, q4 = tree
    a, b = set_text(q3, "A", "B")
    assert mutate(user, "deleteQuestion", q2.id)["__typename"] == "OperationResult"
    assert mutate(user, "deleteAnswerSchemaOption", b.id)["__typename"] == "OperationResult"

    payload = detail(user, survey)
    by_section = {int(s["id"]): s for s in payload["sections"]}
    assert [int(q["id"]) for q in by_section[s1.id]["questions"]] == [q1.id]
    q3_flat = next(q for q in payload["questions"] if int(q["id"]) == q3.id)
    q3_nested = next(q for q in by_section[s2.id]["questions"] if int(q["id"]) == q3.id)
    assert [int(o["id"]) for o in q3_flat["answerSchema"]["options"]] == [a.id]
    assert [int(o["id"]) for o in q3_nested["answerSchema"]["options"]] == [a.id]
    assert q2.id not in {int(q["id"]) for q in payload["questions"]}


def test_the_optimizer_runs_with_prefetch_custom_queryset():
    from strawberry_django.optimizer import DjangoOptimizerExtension

    from surveys import schema as schema_module

    [optimizer] = [e for e in schema_module.schema.extensions if isinstance(e, DjangoOptimizerExtension)]
    assert optimizer.prefetch_custom_queryset is True


def test_a_new_enrolment_excludes_deleted_rows_and_an_existing_one_is_untouched(user, user2, survey, tree):
    s1, s2, q1, q2, q3, q4 = tree
    a, b = set_text(q4, "A", "B")
    existing, _ = enroll_user_in_assessment(user, survey.id)
    snapshot = (
        sorted(UserSection.objects.filter(user_survey=existing).values_list("id", "origin_id")),
        sorted(UserQuestion.objects.filter(user_survey=existing).values_list("id", "origin_id", "order")),
        sorted(UserAnswerOption.objects.filter(user_survey=existing).values_list("id", "origin_id")),
    )

    assert mutate(user, "deleteSection", s1.id)["__typename"] == "OperationResult"
    assert mutate(user, "deleteAnswerSchemaOption", b.id)["__typename"] == "OperationResult"

    assert snapshot == (
        sorted(UserSection.objects.filter(user_survey=existing).values_list("id", "origin_id")),
        sorted(UserQuestion.objects.filter(user_survey=existing).values_list("id", "origin_id", "order")),
        sorted(UserAnswerOption.objects.filter(user_survey=existing).values_list("id", "origin_id")),
    )
    fresh, _ = enroll_user_in_assessment(user2, survey.id)
    assert set(UserSection.objects.filter(user_survey=fresh).values_list("origin_id", flat=True)) == {s2.id}
    assert set(UserQuestion.objects.filter(user_survey=fresh).values_list("origin_id", flat=True)) == {q3.id, q4.id}
    assert b.id not in set(UserAnswerOption.objects.filter(user_survey=fresh).values_list("origin_id", flat=True))
    assert a.id in set(UserAnswerOption.objects.filter(user_survey=fresh).values_list("origin_id", flat=True))


def test_duplicate_survey_copies_live_rows_only(user, survey, tree, monkeypatch):
    s1, s2, q1, q2, q3, q4 = tree
    a, b = set_text(q4, "A", "B")
    assert mutate(user, "deleteSection", s1.id)["__typename"] == "OperationResult"
    assert mutate(user, "deleteAnswerSchemaOption", b.id)["__typename"] == "OperationResult"

    monkeypatch.setattr("surveys.schemas.mutations.surveys.ensure_in_org", lambda *a, **k: None)
    fn = SurveyMutations.duplicate_survey
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    info = SimpleNamespace(context=SimpleNamespace(auth_context=None))
    copy = fn(SurveyMutations(), info, id=survey.id, django_user=None).survey

    assert Section.all_objects.filter(survey=copy).count() == 1
    assert Question.all_objects.filter(survey=copy).count() == 2
    assert sorted(AnswerSchemaOption.all_objects.filter(survey=copy, question__title="Q4").values_list("text", flat=True)) == ["A"]
    assert not Question.all_objects.filter(survey=copy, deleted_at__isnull=False).exists()


def test_the_type_change_option_replacement_stays_a_hard_delete(survey, tree):
    s1, s2, q1, *_ = tree
    ids = [o.pk for o in options_of(q1)]
    q1.type = Question.QUESTION_TYPE_TEXT
    q1.save()
    q1.update_answer_schema()

    assert not AnswerSchemaOption.all_objects.filter(pk__in=ids).exists()


@pytest.mark.parametrize("name, kind", [
    ("deleteSection", "section"), ("deleteQuestion", "question"), ("deleteAnswerSchemaOption", "option"),
])
def test_each_delete_locks_the_survey_before_its_guard(user, survey, tree, monkeypatch, name, kind):
    from django.db.models.query import QuerySet

    from surveys import soft_delete as soft_delete_module
    from surveys.models import Survey

    s1, s2, q1, *_ = tree
    target = {"section": s1, "question": q1, "option": options_of(q1)[0]}[kind]
    calls = []
    real_lock = QuerySet.select_for_update
    real_soft_delete = soft_delete_module.soft_delete

    def lock(self, *a, **k):
        calls.append(("lock", self.model))
        return real_lock(self, *a, **k)

    def soft_delete(kind_, obj, survey_id):
        calls.append(("soft_delete", kind_))
        return real_soft_delete(kind_, obj, survey_id)

    monkeypatch.setattr(QuerySet, "select_for_update", lock)
    for module in ("questions", "sections", "answer_schemas"):
        monkeypatch.setattr(f"surveys.schemas.mutations.{module}.soft_delete", soft_delete)

    assert mutate(user, name, target.id)["__typename"] == "OperationResult"
    assert calls == [("lock", Survey), ("soft_delete", kind)]


def test_a_legacy_question_without_survey_id_renumbers_its_sections_survey(user, survey, tree):
    s1, s2, q1, q2, q3, q4 = tree
    Question.all_objects.filter(pk=q2.pk).update(survey=None)
    # Called below its permission check: `_type_from_question_id` reads `question.survey`, which
    # a legacy row does not have, so the GraphQL path cannot reach this row at all.
    from surveys.schemas.mutations.questions import QuestionMutations

    fn = QuestionMutations.delete_question
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    assert fn(QuestionMutations(), None, id=q2.id).success

    assert Question.all_objects.get(pk=q2.pk).deleted_at is not None
    assert list(Question.objects.filter(survey=survey).order_by("order").values_list("id", "order")) == [
        (q1.id, 1), (q3.id, 2), (q4.id, 3),
    ]


def test_a_referrer_without_a_position_is_named_with_a_question_mark(user, survey, tree):
    s1, s2, q1, q2, q3, q4 = tree
    yes, = set_text(q1, "Yes")
    jump(yes, q3)
    Question.all_objects.filter(pk=q1.pk).update(order=None)

    refused = mutate(user, "deleteQuestion", q3.id)
    assert [m["message"] for m in refused["messages"]] == ["Question ? — Yes"]


def test_a_referrer_under_a_deleted_section_does_not_block(user, survey, tree):
    s1, s2, q1, q2, q3, q4 = tree
    opt, = options_of(q1)
    jump(opt, q3)
    # The pre-backfill shape: the section is stamped, its question and option are not.
    from django.utils import timezone
    Section.all_objects.filter(pk=s1.pk).update(deleted_at=timezone.now())

    assert mutate(user, "deleteQuestion", q3.id)["__typename"] == "OperationResult"


def test_enrolment_drops_an_option_section_column_naming_a_deleted_section(user, survey, tree):
    s1, s2, q1, q2, q3, q4 = tree
    stale, = options_of(q3)
    AnswerSchemaOption.all_objects.filter(pk=stale.pk).update(section=s1)
    assert mutate(user, "deleteSection", s1.id)["__typename"] == "OperationResult"
    assert AnswerSchemaOption.objects.filter(pk=stale.pk).exists()

    fresh, _ = enroll_user_in_assessment(user, survey.id)

    assert not UserSection.objects.filter(user_survey=fresh, origin_id=s1.id).exists()
    copied = UserAnswerOption.objects.get(user_survey=fresh, origin_id=stale.id)
    assert copied.section_id is None
