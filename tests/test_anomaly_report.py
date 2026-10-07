"""The regrade anomaly report counts what explains survey 182 and the max <= 0 attempts, and writes
nothing (`forms:AD-10`, `estate:AD-20`)."""

import importlib
import re
from datetime import datetime, timedelta, timezone

import pytest

from surveys.models import AnswerSchemaOption, Question, ScoreBasis, Survey
from surveys.question_order import renumber_questions
from user_surveys.anomaly_report import plan_max_not_positive, plan_survey_182
from user_surveys.models import UserAnswer, UserAnswerOption, UserQuestion, UserSurvey
from user_surveys.services import enroll_user_in_assessment, max_score

T1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
_MAX = (
    r"attempts=\d+ score_positive=\d+ manual=\d+ no_questions=\d+ orphan_answer=\d+ no_positive_option=\d+ negative_option=\d+"
    r" basis_all=\d+ basis_reached=\d+ basis_answered=\d+ positive_not_counted=\d+"
)
LINE = re.compile(
    r"^anomaly_report (start \(nothing written\)"
    r"|first_vs_later survey=\d+ first_scored=\d+ first_unscored=\d+ later_scored=\d+ later_unscored=\d+ null_user=\d+"
    rf"|max_not_positive survey=\d+ {_MAX}"
    rf"|max_not_positive summary: surveys=\d+ {_MAX})$"
)
ZERO_182 = "anomaly_report first_vs_later survey=182 first_scored=0 first_unscored=0 later_scored=0 later_unscored=0 null_user=0"
ZERO_SUMMARY = (
    "anomaly_report max_not_positive summary: surveys=0 attempts=0 score_positive=0 manual=0 no_questions=0"
    " orphan_answer=0 no_positive_option=0 negative_option=0 basis_all=0 basis_reached=0 basis_answered=0"
    " positive_not_counted=0"
)


@pytest.fixture(autouse=True)
def _distinctive_attempt_ids(db):
    """Push attempt pks past 5000 so one can never pass for a count or a survey id."""
    UserSurvey.objects.create(id=5000).delete()


def _make_survey(like, **fields):
    return Survey.objects.create(
        organization_id=like.organization_id,
        primary_language="en",
        survey_type=like.survey_type,
        display_option=like.display_option,
        evaluation_type=like.evaluation_type,
        use_score=True,
        **fields,
    )


@pytest.fixture
def survey_182(survey):
    return _make_survey(survey, id=182)


def _worth(survey, *scores):
    """One radio question per entry, each with a single option scoring that much."""
    questions = []
    for i, m in enumerate(scores):
        q = Question.objects.create(survey=survey, section=None, title=f"q{i}", type=Question.QUESTION_TYPE_RADIO_MCQ)
        q.answer_schema.options.all().delete()
        AnswerSchemaOption.objects.create(schema=q.answer_schema, survey_id=survey.id, question_id=q.id, score=m)
        questions.append(q)
    renumber_questions(survey.id, [q.id for q in questions])
    return questions


def _attempt(user, survey, score, submitted_at=T1, **fields):
    us, _ = enroll_user_in_assessment(user, survey.id)
    UserSurvey.objects.filter(pk=us.pk).update(score=score, submitted_at=submitted_at, **fields)
    us.refresh_from_db()
    return us


def _snapshot():
    return (
        sorted(UserSurvey.objects.values_list("id", "user_id", "score", "submitted_at", "use_score", "evaluation_type")),
        sorted(UserQuestion.objects.values_list("id", "on_path")),
        sorted(UserAnswer.objects.values_list("id", "question_id", "score")),
        sorted(UserAnswerOption.objects.values_list("id", "score")),
    )


def _run(capsys):
    forbidden = {str(pk) for pk in UserSurvey.objects.values_list("pk", flat=True)}
    forbidden |= {str(u) for u in UserSurvey.objects.values_list("user_id", flat=True) if u}
    before = _snapshot()
    importlib.import_module("user_surveys.migrations.0031_report_regrade_anomalies").forwards(None, None)
    assert _snapshot() == before
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines and all(LINE.match(line) for line in lines), lines
    tokens = set(re.findall(r"[\w-]+", out))
    assert not tokens & forbidden
    return out


def _max_line(
    survey, attempts=1, positive=0, manual=0, no_q=0, orphan=0, no_pos=0, neg=0, b_all=0, reached=1, answered=0, not_counted=0
):
    return (
        f"anomaly_report max_not_positive survey={survey.id} attempts={attempts} score_positive={positive}"
        f" manual={manual} no_questions={no_q} orphan_answer={orphan} no_positive_option={no_pos}"
        f" negative_option={neg} basis_all={b_all} basis_reached={reached} basis_answered={answered}"
        f" positive_not_counted={not_counted}"
    )


def test_empty_reports_a_182_line_and_a_summary_of_zeros(capsys):
    out = _run(capsys)

    assert out.splitlines()[1:] == [ZERO_182, ZERO_SUMMARY]


def test_182_first_unscored_and_later_scored(user, survey_182, capsys):
    _attempt(user, survey_182, None)
    _attempt(user, survey_182, 30, submitted_at=T1 + timedelta(hours=1))

    out = _run(capsys)

    assert (
        "anomaly_report first_vs_later survey=182 first_scored=0 first_unscored=1 later_scored=1"
        " later_unscored=0 null_user=0"
    ) in out


def test_182_scored_first_and_unscored_later_and_open_attempts(user, user2, survey_182):
    _attempt(user, survey_182, 30)
    _attempt(user, survey_182, 30, submitted_at=T1 + timedelta(hours=1), use_score=False)
    _attempt(user2, survey_182, 30, submitted_at=None)

    assert plan_survey_182() == {
        "survey_id": 182, "first_scored": 1, "first_unscored": 0,
        "later_scored": 0, "later_unscored": 1, "null_user": 0,
    }


def test_182_deleted_user_counts_only_as_null_user(user, survey_182):
    us = _attempt(user, survey_182, 30)
    UserSurvey.objects.filter(pk=us.pk).update(user=None)

    assert plan_survey_182() == {
        "survey_id": 182, "first_scored": 0, "first_unscored": 0,
        "later_scored": 0, "later_unscored": 0, "null_user": 1,
    }


def test_182_ignores_other_surveys(user, survey, survey_182):
    _worth(survey, 10)
    _attempt(user, survey, 5)

    assert plan_survey_182()["first_scored"] == 0
    assert plan_survey_182(survey.id)["first_scored"] == 1


def test_manual_override_on_unscored_options(user, survey, capsys):
    _worth(survey, 0)
    _attempt(user, survey, 5, evaluation_type=UserSurvey.EVALUATION_TYPE_MANUAL)

    out = _run(capsys)

    assert _max_line(survey, positive=1, manual=1, no_pos=1) in out
    assert (
        "anomaly_report max_not_positive summary: surveys=1 attempts=1 score_positive=1 manual=1 no_questions=0"
        " orphan_answer=0 no_positive_option=1 negative_option=0 basis_all=0 basis_reached=1 basis_answered=0"
        " positive_not_counted=0"
    ) in out


def test_orphan_answer_with_a_selected_option(user, survey):
    _worth(survey, 0)
    us = _attempt(user, survey, 0)
    answer = UserAnswer.objects.create(user_survey=us, question=None)
    answer.selected_options.add(UserAnswerOption.objects.filter(user_survey=us).first())
    # An orphan answer with nothing selected is not counted.
    empty = UserAnswer.objects.create(user_survey=us, question=None)
    assert empty.selected_options.count() == 0

    assert plan_max_not_positive() == [{
        "survey_id": survey.id, "attempts": 1, "score_positive": 0, "manual": 0, "no_questions": 0,
        "orphan_answer": 1, "no_positive_option": 1, "negative_option": 0,
        "basis_all": 0, "basis_reached": 1, "basis_answered": 0, "positive_not_counted": 0,
    }]


def test_no_snapshot_questions(user, survey, capsys):
    _worth(survey, 10)
    us = _attempt(user, survey, 0)
    UserQuestion.objects.filter(user_survey=us).delete()

    assert _max_line(survey, no_q=1, no_pos=1) in _run(capsys)


def test_negative_option(user, survey):
    _worth(survey, -3)
    _attempt(user, survey, -3)

    assert plan_max_not_positive() == [{
        "survey_id": survey.id, "attempts": 1, "score_positive": 0, "manual": 0, "no_questions": 0,
        "orphan_answer": 0, "no_positive_option": 1, "negative_option": 1,
        "basis_all": 0, "basis_reached": 1, "basis_answered": 0, "positive_not_counted": 0,
    }]


def test_positive_max_unscored_and_later_attempts_are_not_counted(user, user2, survey, capsys):
    zero = _make_survey(survey)
    _worth(survey, 10)
    _worth(zero, 0)
    _attempt(user, survey, 5)
    _attempt(user2, zero, 0, use_score=False)
    _attempt(user, zero, None)
    _attempt(user, zero, 0, submitted_at=T1 + timedelta(hours=1))

    out = _run(capsys)

    assert out.splitlines()[-1] == ZERO_SUMMARY
    assert "max_not_positive survey=" not in out


def test_surveys_are_sorted_by_id(user, survey):
    second = _make_survey(survey)
    for s in (second, survey):
        _worth(s, 0)
        _attempt(user, s, 0)

    assert [row["survey_id"] for row in plan_max_not_positive()] == sorted([survey.id, second.id])


def test_basis_drops_the_positive_question(user, survey, capsys):
    zero, _ = _worth(survey, 0, 10)
    Survey.objects.filter(pk=survey.pk).update(score_basis=ScoreBasis.ANSWERED)
    us = _attempt(user, survey, 0)
    # Answer only the zero-scoring question: the 10-point one is unanswered, so the max is 0.
    zero_q = UserQuestion.objects.get(user_survey=us, origin_id=zero.id)
    answer = UserAnswer.objects.create(user_survey=us, question=zero_q)
    answer.selected_options.add(UserAnswerOption.objects.get(user_survey=us, schema__question=zero_q))
    assert max_score(us) == 0

    out = _run(capsys)

    assert _max_line(survey, reached=0, answered=1, not_counted=1) in out


def test_off_path_positive_question_under_reached(user, survey):
    _, off = _worth(survey, 0, 10)
    us = _attempt(user, survey, 0)
    UserQuestion.objects.filter(user_survey=us, origin_id=off.id).update(on_path=False)

    [row] = plan_max_not_positive()
    assert (row["basis_reached"], row["positive_not_counted"], row["no_positive_option"]) == (1, 1, 0)


def test_basis_all_counts_every_question(user, survey):
    _worth(survey, 0)
    Survey.objects.filter(pk=survey.pk).update(score_basis=ScoreBasis.ALL)
    _attempt(user, survey, 0)

    [row] = plan_max_not_positive()
    assert (row["basis_all"], row["basis_reached"], row["positive_not_counted"]) == (1, 0, 0)
