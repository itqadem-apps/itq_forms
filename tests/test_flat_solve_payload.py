"""Story survey-flow 1.7 — the solve payload is one flat ordered list (`forms:AD-18`).

`userSurvey.questions` is the solver's list: every snapshot question in snapshot order, each with
its `sectionId` or null. `nextQuestionId` / `prevQuestionId`, the learner PDF and the author-side
`survey.questions` read the same order.

Until story 1.6's backfill, question orders are section-scoped, so the order is the legacy key
`(section.order nulls last, order, id)` and a sectionless question sorts last. Once orders are
survey-wide, a sectionless question sits where its `order` puts it, between sections.

Sectionless rows are produced with `.update(section=None)`, which keeps these tests independent of
the story 1.3 author path.
"""

import pytest
from django.utils.timezone import now

from app.platform import PUBLIC_STATUS
from surveys.models import Question, Section
from surveys.question_order import flat_question_ids
from user_surveys.models import UserAnswer, UserQuestion
from user_surveys.services import enroll_user_in_assessment


SOLVE_QUERY = """
query Solve($input: UserSurveysListInput!) {
  userSurvey(userSurveysListInput: $input) {
    items {
      questions { id sectionId nextQuestionId prevQuestionId }
      sections { id questions { id } }
    }
  }
}
"""

PREVIEW_QUERY = """
query Preview($id: ID!) {
  survey(id: $id) {
    questions { id sectionId section { id } nextQuestionId prevQuestionId }
  }
}
"""


class _Identity:
    def __init__(self, user):
        self.subject_str = user.id
        self.email_str = user.email
        self.preferred_username = user.username
        self.first_name = ""
        self.last_name = ""


class _Context:
    def __init__(self, user=None):
        self.request = None
        self.identity = _Identity(user) if user else None
        self.auth_context = None
        self.currency = None


def _execute(query, variables, user=None):
    from surveys import schema as schema_module

    result = schema_module.schema.execute_sync(
        query, variable_values=variables, context_value=_Context(user)
    )
    assert result.errors is None, result.errors
    return result.data


def _solve(user, user_survey):
    data = _execute(
        SOLVE_QUERY,
        {"input": {"limit": 1, "offset": 0, "filters": {"id": user_survey.id}, "sort": None}},
        user,
    )
    return data["userSurvey"]["items"][0]


@pytest.fixture
def tree(survey):
    """Section A (two questions), section B (two questions), section C (one question)."""
    a = Section.objects.create(survey=survey, title="A")
    b = Section.objects.create(survey=survey, title="B")
    c = Section.objects.create(survey=survey, title="C")
    for sec in (a, b):
        Question.objects.create(survey=survey, section=sec, title=f"{sec.title}2", type="text")
    return a, b, c


def _snapshot(user, survey):
    user_survey, _ = enroll_user_in_assessment(user, survey.id)
    return user_survey


def _legacy_ids(user_survey):
    return [
        uq.id
        for uq in UserQuestion.objects.filter(user_survey=user_survey)
        .select_related("section")
        .order_by("section__order", "order", "id")
    ]


def test_no_sectionless_question_order_is_unchanged(user, survey, tree):
    user_survey = _snapshot(user, survey)
    payload = _solve(user, user_survey)

    ids = [int(q["id"]) for q in payload["questions"]]
    assert ids == _legacy_ids(user_survey)
    assert [int(q["id"]) for s in payload["sections"] for q in s["questions"]] == ids


def test_section_scoped_orders_put_a_sectionless_question_last(user, survey, tree):
    """Pre-backfill: orders are 1..k per section, so they collide and give no survey-wide
    position — the legacy key holds and the sectionless question is delivered last."""
    a, b, c = tree
    # A survey no author has saved since story 1.2 still holds section-scoped orders.
    for sec in (a, b, c):
        for i, pk in enumerate(sec.questions.order_by("order", "id").values_list("id", flat=True), start=1):
            Question.objects.filter(pk=pk).update(order=i)
    user_survey = _snapshot(user, survey)
    moved = UserQuestion.objects.filter(user_survey=user_survey, section__origin_id=b.id).order_by("order").first()
    UserQuestion.objects.filter(pk=moved.pk).update(section=None)

    payload = _solve(user, user_survey)
    ids = [int(q["id"]) for q in payload["questions"]]

    assert moved.id in ids, "a sectionless snapshot question is delivered"
    assert ids[-1] == moved.id
    assert payload["questions"][-1]["sectionId"] is None
    assert len(ids) == UserQuestion.objects.filter(user_survey=user_survey).count()


def _make_survey_wide(user_survey):
    """What story 1.6's backfill writes: 1..N across the snapshot in legacy order."""
    for i, pk in enumerate(_legacy_ids(user_survey), start=1):
        UserQuestion.objects.filter(pk=pk).update(order=i)


def test_survey_wide_orders_keep_a_sectionless_question_between_sections(user, survey, tree):
    a, b, c = tree
    user_survey = _snapshot(user, survey)
    _make_survey_wide(user_survey)
    expected = _legacy_ids(user_survey)
    # B's questions sit at positions 3-4; take B out of the survey, leaving them sectionless
    # between A and C — what story 1.5 does to a hidden section's questions.
    b_ids = list(
        UserQuestion.objects.filter(user_survey=user_survey, section__origin_id=b.id).values_list("id", flat=True)
    )
    UserQuestion.objects.filter(pk__in=b_ids).update(section=None)

    payload = _solve(user, user_survey)
    ids = [int(q["id"]) for q in payload["questions"]]
    assert ids == expected
    assert [q["sectionId"] for q in payload["questions"]][2:4] == [None, None]
    # `sections` still heads only its own questions; the sectionless ones are not in it.
    assert [int(q["id"]) for s in payload["sections"] for q in s["questions"]] == [
        pk for pk in expected if pk not in b_ids
    ]

    # next/prev walk the same list, sectionless questions included.
    for i, q in enumerate(payload["questions"]):
        nxt = ids[i + 1] if i + 1 < len(ids) else None
        prv = ids[i - 1] if i > 0 else None
        assert q["nextQuestionId"] == nxt
        assert q["prevQuestionId"] == prv


def test_a_shuffled_snapshot_keeps_the_legacy_order(user, survey, tree):
    """`randomize_questions` numbers sectioned questions 1..k across sections, interleaving them.
    Unique orders alone must not switch to `(order, id)`, or the sections would be torn apart."""
    a, b, c = tree
    user_survey = _snapshot(user, survey)
    rows = list(UserQuestion.objects.filter(user_survey=user_survey).order_by("section__order", "order"))
    # interleave: A1=1, B1=2, A2=3, B2=4, C1=5, then pull C1 out of its section
    for uq, order in zip(rows, [1, 3, 2, 4, 5]):
        UserQuestion.objects.filter(pk=uq.pk).update(order=order)
    UserQuestion.objects.filter(pk=rows[-1].pk).update(section=None)

    expected = [r.id for r in rows]
    assert flat_question_ids(UserQuestion.objects.filter(user_survey=user_survey)) == expected


def test_a_sectionless_question_inside_a_sections_run_keeps_the_legacy_order(user, survey, tree):
    """Unique orders that would drop a sectionless question into the middle of a section must not
    split it: the legacy key holds."""
    user_survey = _snapshot(user, survey)
    _make_survey_wide(user_survey)
    expected = _legacy_ids(user_survey)
    # Spread A2..B2 to 10..30, then give C1 no section and order 5 — between A1 and A2.
    UserQuestion.objects.filter(pk=expected[1]).update(order=10)
    UserQuestion.objects.filter(pk=expected[2]).update(order=20)
    UserQuestion.objects.filter(pk=expected[3]).update(order=30)
    UserQuestion.objects.filter(pk=expected[4]).update(section=None, order=5)
    # wide order would be A1, C1(5), A2(10), ... — A split by a sectionless question.
    assert flat_question_ids(UserQuestion.objects.filter(user_survey=user_survey)) == (
        expected[:4] + [expected[4]]
    )


def test_pdf_lists_answers_in_snapshot_order_including_sectionless(user, survey, tree):
    from user_surveys.pdf_service import _build_context

    a, b, c = tree
    user_survey = _snapshot(user, survey)
    _make_survey_wide(user_survey)
    expected = _legacy_ids(user_survey)
    UserQuestion.objects.filter(user_survey=user_survey, section__origin_id=b.id).update(section=None)
    for pk in reversed(expected):
        uq = UserQuestion.objects.get(pk=pk)
        uq.translations = {"default": {"title": f"Q{pk}"}}
        uq.save(update_fields=["translations"])
        UserAnswer.objects.create(user=user, user_survey=user_survey, question=uq, answer="x")
    user_survey.submitted_at = now()
    user_survey.save(update_fields=["submitted_at"])

    context = _build_context(user_survey)
    assert [item["question_title"] for item in context["answers"]] == [f"Q{pk}" for pk in expected]


def test_author_preview_flat_list_in_survey_wide_order(survey, tree):
    a, b, c = tree
    survey.status = PUBLIC_STATUS
    survey.save(update_fields=["status"])
    deleted = Question.objects.create(survey=survey, section=c, title="gone", type="text")
    questions = list(
        Question.objects.filter(survey=survey).exclude(pk=deleted.pk).order_by("section__order", "order", "id")
    )
    for i, q in enumerate(questions, start=1):
        Question.objects.filter(pk=q.pk).update(order=i)
    # A soft-deleted question is not in the list, and its colliding order does not count.
    Question.objects.filter(pk=deleted.pk).update(deleted_at=now(), order=1)
    b_ids = [q.id for q in questions if q.section_id == b.id]
    Question.objects.filter(pk__in=b_ids).update(section=None)

    payload = _execute(PREVIEW_QUERY, {"id": str(survey.id)})["survey"]["questions"]
    assert [int(q["id"]) for q in payload] == [q.id for q in questions]
    _assert_walk(payload)
    for q in payload:
        if int(q["id"]) in b_ids:
            assert q["sectionId"] is None and q["section"] is None
        else:
            assert q["section"] is not None and q["section"]["id"] == q["sectionId"]

    # A soft-deleted section takes its (still live) questions out of the preview.
    Section.objects.filter(pk=c.pk).update(deleted_at=now())
    payload = _execute(PREVIEW_QUERY, {"id": str(survey.id)})["survey"]["questions"]
    assert [int(q["id"]) for q in payload] == [q.id for q in questions if q.section_id != c.id]
    _assert_walk(payload)


def _assert_walk(payload):
    ids = [int(q["id"]) for q in payload]
    for i, q in enumerate(payload):
        assert q["nextQuestionId"] == (ids[i + 1] if i + 1 < len(ids) else None)
        assert q["prevQuestionId"] == (ids[i - 1] if i > 0 else None)


def test_author_next_prev_unchanged_without_sectionless_questions(survey, tree):
    """No sectionless question: the author walk is today's `(section.order, order)` walk."""
    survey.status = PUBLIC_STATUS
    survey.save(update_fields=["status"])
    legacy = list(
        Question.objects.filter(survey=survey, section__isnull=False, deleted_at__isnull=True)
        .order_by("section__order", "order")
        .values_list("id", flat=True)
    )

    payload = _execute(PREVIEW_QUERY, {"id": str(survey.id)})["survey"]["questions"]
    assert [int(q["id"]) for q in payload] == legacy
    _assert_walk(payload)
