"""Story survey-flow 2.8 — the seeded fixture branches, and proves it end to end (`forms:AD-3`,
`forms:AD-4`, `forms:AD-10`, `forms:AD-15`, `forms:AD-16`, `forms:AD-19`).

The real seed command runs into the test DB, and learners are driven through the real
`answer_question` resolver, `advance`, `finish_assessment` and `_build_context`.
"""

import io
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.db import transaction
from django.test import RequestFactory

from conftest import ORG
from surveys.inputs import AnswerSchemaOptionInput
from surveys.flow import assert_survey_forward, validate_edge
from surveys.models import AnswerSchemaOption, FlowAction, Question, ScoreBasis, Section, Survey, SurveyTranslation
from surveys.question_order import flat_question_ids, renumber_questions
from surveys.management.commands.seed_test_surveys import TAG
from surveys.schemas.mutations.answer_schemas import AnswerSchemaMutations
from user_surveys.models import Child, UserAnswer, UserAnswerOption, UserQuestion, UserSurvey
from user_surveys.pdf_service import _build_context
from user_surveys.schemas.mutations.answer_question import AnswerQuestionMutation
from user_surveys.services import enroll_user_in_assessment, finish_assessment
from user_surveys.types import EndReason, UserAnswerType
from user_surveys.types.user_survey import AttemptEnded, NextQuestion

BRANCHING = f"{TAG}Section Jump Navigation"
SCORED = f"{TAG}Section Jump Navigation (Scored)"


# ── Helpers (the idiom of tests/test_flow_advance.py) ────────────────


def _resolver(cls, name):
    field = next(f for f in cls.__strawberry_definition__.fields if f.python_name == name)
    fn = field.base_resolver.wrapped_func
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def _mutation(cls, name):
    fn = getattr(cls, name)
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def _update(option, **fields):
    with transaction.atomic():
        return _mutation(AnswerSchemaMutations, "update_answer_schema_option")(
            AnswerSchemaMutations(), None, id=option.id, input=AnswerSchemaOptionInput(**fields), django_user=None
        )


# Anti-cheat surveys read the request off `info` on every answer.
_INFO = SimpleNamespace(context=SimpleNamespace(request=RequestFactory().post("/graphql")))


def _enrol(user, survey, child=None):
    us, _ = enroll_user_in_assessment(user, survey.id, child=child)
    return us


def _mine(us, question):
    return UserQuestion.objects.get(user_survey=us, origin_id=question.id)


def _submit(us, uq, values):
    return _resolver(AnswerQuestionMutation, "answer_question")(
        AnswerQuestionMutation(), _INFO, user_survey_id=str(us.id), question_id=str(uq.id),
        answer=values, django_user=us.user,
    )


def _answer(us, question, option=None, text=None):
    if option is not None:
        values = [str(UserAnswerOption.objects.get(user_survey=us, origin_id=option.id).id)]
    else:
        values = [text or "x"]
    return _submit(us, _mine(us, question), values)


def _answer_any(us, uq):
    """Answer a snapshot question with its first choice, whatever its type."""
    options = UserAnswerOption.objects.filter(schema__question=uq).order_by("order", "id")
    if uq.type in UserQuestion.GRID_TYPES:
        row = options.filter(is_row=True).first()
        column = options.filter(is_column=True).first()
        return _submit(us, uq, [f"{row.id}-{column.id}"])
    if uq.type in UserQuestion.MCQ_TYPES:
        return _submit(us, uq, [str(options.first().id)])
    return _submit(us, uq, ["x"])


def _advance(user_answer):
    return _resolver(UserAnswerType, "advance")(user_answer)


def _on_path(us):
    return {q.origin_id for q in UserQuestion.objects.filter(user_survey=us, on_path=True)}


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
        self.auth_context = None
        self.currency = None


def _max_score_field(user, us):
    from surveys import schema as schema_module

    result = schema_module.schema.execute_sync(
        """query R($input: UserSurveysListInput!) {
          userSurvey(userSurveysListInput: $input) { items { score maxScore scoreBasis } }
        }""",
        variable_values={"input": {"limit": 1, "offset": 0, "filters": {"id": us.id}, "sort": None}},
        context_value=_Context(user),
    )
    assert result.errors is None, result.errors
    return result.data["userSurvey"]["items"][0]


def _top(question):
    return question.answer_schema.options.order_by("-score", "id").first()


def _top_score(*questions):
    return sum(_top(q).score for q in questions)


# ── The seeded fixture ───────────────────────────────────────────────


@pytest.fixture
def seeded():
    """The surveys the seed command created, by English title. Survey 10 renames its English title
    to one without `TAG`, so a `TAG` prefix filter alone would miss it; the rows are scoped to the
    command's own output instead, and the prefix is checked on everything else."""
    before = set(Survey.objects.values_list("id", flat=True))
    call_command("seed_test_surveys", "--organization-id", str(ORG), stdout=io.StringIO())
    created = {
        t.title: t.survey
        for t in SurveyTranslation.objects.filter(language="en").exclude(survey_id__in=before).select_related("survey")
    }
    assert {title for title in created if not title.startswith(TAG)} == {"Demographics Survey"}
    return created


def _tree(survey):
    """Q0, S1, S2, S3, P1, C1 of a branching survey, plus the Yes and No options of Q0."""
    by_title = {q.title: q for q in Question.objects.filter(survey=survey)}
    q0 = by_title["Are you a student?"]
    yes, no = q0.answer_schema.options.order_by("order")
    return SimpleNamespace(
        q0=q0, s1=by_title["University name"], s2=by_title["Field of study"], s3=by_title["Year of study"],
        p1=by_title["Company name"], c1=by_title["Email address"], yes=yes, no=no,
    )


@pytest.fixture
def s8(seeded):
    return _tree(seeded[BRANCHING])


@pytest.fixture
def s11(seeded):
    return _tree(seeded[SCORED])


def _student(t):
    return {t.q0.id, t.s1.id, t.s2.id, t.s3.id, t.c1.id}


def _professional(t):
    return {t.q0.id, t.p1.id, t.c1.id}


def _low(question):
    return question.answer_schema.options.order_by("score", "id").first()


def _no_then_back_to_yes(us, t, scored):
    """Answer No and P1, go back, answer Yes and the student branch, then submit."""
    _answer(us, t.q0, t.no)
    _answer(us, t.p1, _top(t.p1) if scored else None)
    _answer(us, t.q0, t.yes)
    for q in (t.s1, t.s2, t.s3, t.c1):
        _answer(us, q, _top(q) if (scored or q is t.s3) else None)
    finish_assessment(us)
    us.refresh_from_db()


STEP_CAP = 20


def _walk(us, first_answer):
    """Follow `advance` from `first_answer` to the end, answering each question it returns.
    Returns the origin ids shown and the final step; a forward-only path cannot loop, and the cap
    turns a regression that does into a failure instead of a hang."""
    shown = []
    step = _advance(first_answer)
    for _ in range(STEP_CAP):
        if not isinstance(step, NextQuestion):
            return shown, step
        uq = UserQuestion.objects.get(pk=step.question_id)
        shown.append(uq.origin_id)
        step = _advance(_answer_any(us, uq))
    pytest.fail(f"advance did not end within {STEP_CAP} steps: {shown}")


# ── The seed ─────────────────────────────────────────────────────────


def _assert_branching_shape(survey):
    """Survey 8's shape (and survey 11's): survey-wide numbering (`forms:AD-4`), exactly two option
    edges (`forms:AD-3`), and no legacy section jump (`forms:AD-15`)."""
    order = list(Question.objects.filter(survey=survey).order_by("order").values_list("title", "order"))
    assert order == [
        ("Are you a student?", 1), ("University name", 2), ("Field of study", 3),
        ("Year of study", 4), ("Company name", 5), ("Email address", 6),
    ]
    edges = list(
        AnswerSchemaOption.objects.filter(survey=survey)
        .exclude(flow_action=FlowAction.FALL_THROUGH)
        .order_by("question__order", "order")
        .values_list("question__title", "text", "flow_action", "flow_target__title")
    )
    assert edges == [("Are you a student?", "No", FlowAction.GO_TO, "Company name")] + [
        ("Year of study", year, FlowAction.GO_TO, "Email address")
        for year in ("First", "Second", "Third", "Fourth or later")
    ]
    assert list(
        AnswerSchemaOption.objects.filter(survey=survey, question__title="Are you a student?", text="Yes")
        .values_list("flow_action", "flow_target")
    ) == [(FlowAction.FALL_THROUGH, None)]
    assert set(Section.objects.filter(survey=survey).values_list("submit_action", "submit_action_target")) == {
        ("next", None)
    }


def test_seed_creates_eleven_surveys_and_survey_8_routes_only_by_option_edges(seeded):
    assert len(seeded) == 11 and BRANCHING in seeded and SCORED in seeded
    _assert_branching_shape(seeded[BRANCHING])


def test_survey_11_is_the_scored_twin(seeded, s11):
    survey = seeded[SCORED]
    _assert_branching_shape(survey)
    assert (survey.survey_type, survey.is_evaluable, survey.use_score) == ("assessment", True, True)
    assert survey.evaluation_type == Survey.EVALUATION_TYPE_AUTOMATIC_EVALUATION
    assert survey.score_basis == ScoreBasis.REACHED
    for q in (s11.q0, s11.s1, s11.s2, s11.s3, s11.p1, s11.c1):
        assert q.type == Question.QUESTION_TYPE_RADIO_MCQ and _top(q).score > 0


def test_every_seeded_edge_passes_the_option_mutation_validators(seeded):
    """The seed writes edges with `.update()`, so it must still produce what the API would accept."""
    for title in (BRANCHING, SCORED):
        survey = seeded[title]
        routed = AnswerSchemaOption.objects.filter(
            survey=survey, flow_action__in=[FlowAction.GO_TO, FlowAction.TERMINATE]
        )
        assert routed.count() == 5
        for option in routed:
            validate_edge(option)
        assert_survey_forward(survey)


def test_the_edge_is_authorable_through_the_option_mutation(user, s8):
    _update(s8.no, flow_action=FlowAction.FALL_THROUGH, flow_target_id=None)
    cleared = AnswerSchemaOption.objects.get(pk=s8.no.pk)
    assert (cleared.flow_action, cleared.flow_target_id) == (FlowAction.FALL_THROUGH, None)

    _update(s8.no, flow_action=FlowAction.GO_TO, flow_target_id=str(s8.p1.id))
    us = _enrol(user, s8.q0.survey)
    _answer(us, s8.q0, s8.no)
    _answer(us, s8.p1)
    _answer(us, s8.c1)
    assert _on_path(us) == _professional(s8)


# ── Two learners, one survey ─────────────────────────────────────────


def test_two_learners_see_different_question_sets(user, user2, s8):
    a = _enrol(user, s8.q0.survey)
    b = _enrol(user2, s8.q0.survey)
    _answer(a, s8.q0, s8.yes)
    _answer(b, s8.q0, s8.no)
    # Until S3 is answered its edge does not route, so P1 still sits on A's path (`forms:AD-19`).
    _answer(a, s8.s1)
    _answer(a, s8.s2)
    _answer(a, s8.s3, _top(s8.s3))

    assert _on_path(a) == _student(s8)
    assert _on_path(b) == _professional(s8)
    assert _on_path(a) != _on_path(b)


def test_the_no_learner_is_never_advanced_to_the_student_questions(user, s8):
    us = _enrol(user, s8.q0.survey)
    shown, end = _walk(us, _answer(us, s8.q0, s8.no))

    assert shown == [s8.p1.id, s8.c1.id]
    assert isinstance(end, AttemptEnded) and end.reason == EndReason.FALLTHROUGH_COMPLETE


def test_the_yes_learner_is_advanced_through_the_student_branch_and_never_to_p1(user, s8):
    us = _enrol(user, s8.q0.survey)
    shown, end = _walk(us, _answer(us, s8.q0, s8.yes))

    assert shown == [s8.s1.id, s8.s2.id, s8.s3.id, s8.c1.id]
    assert s8.p1.id not in shown
    assert isinstance(end, AttemptEnded) and end.reason == EndReason.FALLTHROUGH_COMPLETE


def test_going_back_and_switching_to_yes_puts_the_student_branch_on_the_path(user, s8):
    us = _enrol(user, s8.q0.survey)
    _no_then_back_to_yes(us, s8, scored=False)

    assert us.submitted_at is not None
    assert _on_path(us) == _student(s8)
    assert not _mine(us, s8.p1).on_path


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="story 2.9 prunes off-path answers")
def test_the_submitted_result_holds_no_answer_from_the_abandoned_branch(user, s8):
    us = _enrol(user, s8.q0.survey)
    _no_then_back_to_yes(us, s8, scored=False)
    assert not UserAnswer.objects.filter(user_survey=us, question=_mine(us, s8.p1)).exists()


# ── Scoring the branches (survey 11) ─────────────────────────────────


def _no_learner_misses_c1(user, t):
    """No, P1 at its top option, C1 at its 0 option, then submit."""
    us = _enrol(user, t.q0.survey)
    for q, option in ((t.q0, t.no), (t.p1, _top(t.p1)), (t.c1, _low(t.c1))):
        _answer(us, q, option)
    finish_assessment(us)
    us.refresh_from_db()
    return us


def test_max_score_follows_the_declared_basis(user, user2, s11):
    # Q0's share of the max is its top option, whichever option the learner chose.
    reached = _top_score(s11.q0, s11.p1, s11.c1)
    score = s11.no.score + _top(s11.p1).score + _low(s11.c1).score
    result = _max_score_field(user, _no_learner_misses_c1(user, s11))
    assert result == {"score": score, "maxScore": reached, "scoreBasis": "reached"}
    assert result["score"] < result["maxScore"]

    Survey.objects.filter(pk=s11.q0.survey_id).update(score_basis=ScoreBasis.ALL)
    every = reached + _top_score(s11.s1, s11.s2, s11.s3)
    assert _max_score_field(user2, _no_learner_misses_c1(user2, s11)) == {
        "score": score, "maxScore": every, "scoreBasis": "all",
    }


def test_an_abandoned_branch_answer_does_not_score(user, s11):
    us = _enrol(user, s11.q0.survey)
    _no_then_back_to_yes(us, s11, scored=True)

    student = (s11.s1, s11.s2, s11.s3, s11.c1)
    assert us.score == s11.yes.score + _top_score(*student)
    assert _max_score_field(user, us)["maxScore"] == _top_score(s11.q0, *student)


# ── A formerly hidden assessment, rebuilt sectionless ────────────────


def test_a_sectionless_scored_assessment_renders_its_real_percentage(user, survey):
    """Mirrors the 9 assessments built inside a hidden wrapper section; no production row is read."""
    questions = [
        Question.objects.create(survey=survey, section=None, title=f"q{i}", type=Question.QUESTION_TYPE_RADIO_MCQ)
        for i in (1, 2, 3)
    ]
    renumber_questions(survey.id, [q.id for q in questions])
    picks = []
    for q in questions:
        q.answer_schema.options.all().delete()
        low = AnswerSchemaOption.objects.create(schema=q.answer_schema, survey=survey, question=q, score=0)
        AnswerSchemaOption.objects.create(schema=q.answer_schema, survey=survey, question=q, score=10)
        picks.append(low if q is questions[2] else _top(q))

    us = _enrol(user, survey)
    for q, option in zip(questions, picks):
        _answer(us, q, option)
    finish_assessment(us)
    us.refresh_from_db()

    assert us.score == 20
    context = _build_context(us)
    assert context["max_score"] == 30
    assert context["score_pct"] == round(20 / 30 * 100)


# ── Surveys carrying no flow (`forms:AD-16`) ─────────────────────────


def test_every_seeded_survey_without_a_flow_walks_in_snapshot_order(user, seeded):
    plain = [s for title, s in seeded.items() if title not in (BRANCHING, SCORED)]
    assert len(plain) == 9
    for survey in plain:
        child = Child.objects.create(id=f"child-{survey.id}", name="Child") if survey.is_for_child else None
        us = _enrol(user, survey, child=child)
        order = flat_question_ids(UserQuestion.objects.filter(user_survey=us))
        assert order and set(order) == {q.id for q in UserQuestion.objects.filter(user_survey=us, on_path=True)}

        for i, pk in enumerate(order):
            step = _advance(_answer_any(us, UserQuestion.objects.get(pk=pk)))
            if i + 1 < len(order):
                assert isinstance(step, NextQuestion) and step.question_id == order[i + 1], survey
            else:
                assert isinstance(step, AttemptEnded) and step.reason == EndReason.FALLTHROUGH_COMPLETE, survey
        assert UserQuestion.objects.filter(user_survey=us, on_path=False).count() == 0
