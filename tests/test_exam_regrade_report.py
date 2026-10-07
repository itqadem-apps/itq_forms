"""The exam regrade report prints per-survey counts of what score / max_score would change, and
writes nothing (`forms:AD-10`, `estate:AD-20`)."""

import importlib
import re
from datetime import datetime, timedelta, timezone

import pytest

from surveys.models import AnswerSchemaOption, Question, ScoreBasis, Survey
from surveys.question_order import renumber_questions
from user_surveys.models import UserAnswer, UserAnswerOption, UserQuestion, UserSurvey
from user_surveys.regrade_report import grades
from user_surveys.services import enroll_user_in_assessment, max_score

T1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
_COUNTS = (
    r"candidates=\d+ changed=\d+ score_over_100=\d+ max_not_positive=\d+ first_unscored=\d+ manual_evaluated=\d+"
)
LINE = re.compile(
    rf"^exam_regrade_report (start \(nothing written\)|survey=\d+ {_COUNTS}|summary: surveys=\d+ {_COUNTS})$"
)
ZEROS = "score_over_100=0 max_not_positive=0 first_unscored=0 manual_evaluated=0"


@pytest.fixture(autouse=True)
def _distinctive_attempt_ids(db):
    """Push attempt pks past 5000 so one can never pass for a count or a survey id."""
    UserSurvey.objects.create(id=5000).delete()


def _worth(survey, *maxes):
    """One radio question per entry, each with a single option scoring that much."""
    questions = []
    for i, m in enumerate(maxes):
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
        sorted(
            UserSurvey.objects.values_list(
                "id", "score", "submitted_at", "use_score", "evaluation_type", "evaluated_at"
            )
        ),
        sorted(UserQuestion.objects.values_list("id", "on_path")),
        sorted(UserAnswer.objects.values_list("id", "score")),
        sorted(UserAnswerOption.objects.values_list("id", "score")),
    )


def _forbidden_numbers():
    """Every attempt id, raw score and old/new grade in the database: none may reach the log."""
    values = set()
    for us in UserSurvey.objects.all():
        values.add(us.pk)
        if us.score is not None:
            values.add(us.score)
            values.update(int(g) for g in grades(us.score, max_score(us)) if g == int(g))
    # Counts in these tests stay below 10, so a smaller value cannot be told apart from one.
    return {float(v) for v in values if abs(v) >= 10}


def _run(capsys):
    user_ids = [u for u in UserSurvey.objects.values_list("user_id", flat=True) if u]
    forbidden = _forbidden_numbers()
    assert all(pk > 5000 for pk in UserSurvey.objects.values_list("pk", flat=True))
    before = _snapshot()
    importlib.import_module("user_surveys.migrations.0030_report_exam_regrade").forwards(None, None)
    assert _snapshot() == before
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines and all(LINE.match(line) for line in lines), lines
    for value in user_ids:
        assert value not in out
    # Survey ids are allowed; no other number token may be an attempt id, score or grade.
    tokens = re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])", re.sub(r"survey=\d+", "", out))
    leaked = {float(t) for t in tokens} & forbidden
    assert not leaked, leaked
    return out


def _survey_line(survey, candidates, changed, over=0, zero=0, unscored=0, manual=0):
    return (
        f"exam_regrade_report survey={survey.id} candidates={candidates} changed={changed}"
        f" score_over_100={over} max_not_positive={zero} first_unscored={unscored} manual_evaluated={manual}"
    )


def test_empty_reports_a_summary_of_zeros(capsys):
    out = _run(capsys)

    assert f"exam_regrade_report summary: surveys=0 candidates=0 changed=0 {ZEROS}" in out
    assert "survey=" not in out


def test_30_of_200_changes(user, survey, capsys):
    _worth(survey, 200)
    _attempt(user, survey, 30)

    out = _run(capsys)

    assert _survey_line(survey, 1, 1) in out
    assert f"summary: surveys=1 candidates=1 changed=1 {ZEROS}" in out


def test_50_of_100_is_unchanged(user, survey, capsys):
    _worth(survey, 100)
    _attempt(user, survey, 50)

    assert _survey_line(survey, 1, 0) in _run(capsys)


def test_over_100_points_changes_and_is_counted(user, survey, capsys):
    _worth(survey, 200)
    _attempt(user, survey, 150)

    assert _survey_line(survey, 1, 1, over=1) in _run(capsys)


def test_only_the_first_submitted_attempt_is_judged(user, survey, capsys):
    _worth(survey, 200)
    _attempt(user, survey, 200, submitted_at=T1 + timedelta(hours=1))
    _attempt(user, survey, 30, submitted_at=T1)

    # Judged on the earlier 30/200; the later 200/200 alone would be unchanged.
    assert _survey_line(survey, 1, 1) in _run(capsys)


def test_a_submitted_at_tie_is_broken_by_the_lowest_id(user, survey, capsys):
    _worth(survey, 200)
    _attempt(user, survey, 200)
    _attempt(user, survey, 30)

    # The lower id is 200/200, unchanged; picking the 30/200 would count a change.
    assert _survey_line(survey, 1, 0, over=1) in _run(capsys)


def test_open_unscored_and_null_score_attempts_are_excluded(user, user2, survey, capsys):
    _worth(survey, 200)
    _attempt(user, survey, 30, submitted_at=None)
    _attempt(user2, survey, 30, use_score=False)
    _attempt(user2, survey, None, submitted_at=T1 + timedelta(hours=1))

    out = _run(capsys)

    assert "survey=" not in out
    # user2's first submitted attempt is unscored, so the later one is never judged either.
    assert "summary: surveys=0 candidates=0 changed=0 score_over_100=0 max_not_positive=0 first_unscored=1" in out


def test_a_first_attempt_without_use_score_hides_a_later_scored_one(user, survey, capsys):
    _worth(survey, 200)
    _attempt(user, survey, 30, use_score=False)
    _attempt(user, survey, 30, submitted_at=T1 + timedelta(hours=1))

    out = _run(capsys)

    assert "survey=" not in out
    assert "summary: surveys=0 candidates=0 changed=0 score_over_100=0 max_not_positive=0 first_unscored=1" in out


def test_first_unscored_is_counted_on_a_survey_with_candidates(user, user2, survey, capsys):
    _worth(survey, 200)
    _attempt(user, survey, None)
    _attempt(user2, survey, 30)

    out = _run(capsys)

    assert _survey_line(survey, 1, 1, unscored=1) in out
    assert "summary: surveys=1 candidates=1 changed=1 score_over_100=0 max_not_positive=0 first_unscored=1" in out


def test_manually_evaluated_candidates_are_counted(user, user2, survey, capsys):
    _worth(survey, 200)
    _attempt(user, survey, 30, evaluation_type=UserSurvey.EVALUATION_TYPE_MANUAL)
    _attempt(user2, survey, 50)

    out = _run(capsys)

    assert _survey_line(survey, 2, 2, manual=1) in out
    assert "summary: surveys=1 candidates=2 changed=2 score_over_100=0 max_not_positive=0 first_unscored=0 manual_evaluated=1" in out


def test_zero_max_falls_back_to_the_old_grade(user, survey, capsys):
    _worth(survey, 0)
    _attempt(user, survey, 0)

    assert _survey_line(survey, 1, 0, zero=1) in _run(capsys)


def test_the_max_follows_the_basis(user, survey, capsys):
    _, off = _worth(survey, 100, 100)
    Survey.objects.filter(pk=survey.pk).update(score_basis=ScoreBasis.REACHED)
    us = _attempt(user, survey, 100)
    UserQuestion.objects.filter(user_survey=us, origin_id=off.id).update(on_path=False)

    # Off-path excluded: 100 of 100, unchanged. Counted, it would be 100 of 200 and change.
    assert max_score(us) == 100
    assert _survey_line(survey, 1, 0) in _run(capsys)


def test_surveys_are_counted_separately(user, user2, survey, capsys):
    other = Survey.objects.create(
        organization_id=survey.organization_id,
        primary_language="en",
        survey_type=survey.survey_type,
        display_option=survey.display_option,
        evaluation_type=survey.evaluation_type,
        use_score=True,
    )
    _worth(survey, 200)
    _worth(other, 100)
    _attempt(user, survey, 30)
    _attempt(user2, survey, 200)
    _attempt(user, other, 50)

    out = _run(capsys)

    assert _survey_line(survey, 2, 1, over=1) in out
    assert _survey_line(other, 1, 0) in out
    assert "summary: surveys=2 candidates=3 changed=1 score_over_100=1 max_not_positive=0 first_unscored=0" in out


def test_the_leak_check_catches_a_printed_score(user, survey, capsys, monkeypatch):
    from user_surveys import regrade_report

    _worth(survey, 200)
    _attempt(user, survey, 30)
    describe = regrade_report.describe
    # A well-formed line whose count happens to be the raw score: only the token check sees it.
    monkeypatch.setattr(
        regrade_report, "describe", lambda p: [line.replace("candidates=1 ", "candidates=30 ") for line in describe(p)]
    )

    with pytest.raises(AssertionError, match="leaked|30"):
        _run(capsys)


def test_grades_clamp_and_fall_back():
    assert grades(30, 200) == (30.0, 15.0)
    assert grades(150, 200) == (100.0, 75.0)
    assert grades(-10, 50) == (0.0, 0.0)
    assert grades(0, 0) == (0.0, 0.0)
    assert grades(72, -1) == (72.0, 72.0)
