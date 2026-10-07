"""What explains the two anomalies the exam regrade report turned up (`forms:AD-10`, `estate:AD-20`).

A. courses holds finished exam rows below 100 on lessons bound to survey 182, yet forms has no
   scored first attempt there. `plan_survey_182()` counts every submitted attempt on 182 by
   whether it is the learner's first (as `regrade_report` picks it) and whether it is scored.
B. Scored first attempts whose `max_scores` is 0 or less. `plan_max_not_positive()` counts, per
   survey, the traits that tell the candidate causes apart.

Both only read; `describe()` renders them as deploy-log lines. Survey ids and counts only: no
user, attempt id, score, percentage or timestamp reaches the log.
"""

from collections import defaultdict

from surveys.models import ScoreBasis
from user_surveys.models import UserAnswer, UserAnswerOption, UserQuestion, UserSurvey
from user_surveys.regrade_report import _first_attempts
from user_surveys.services import max_scores

TAG = "anomaly_report"
SURVEY_182 = 182
COUNTS_182 = ("first_scored", "first_unscored", "later_scored", "later_unscored", "null_user")
COUNTS_MAX = (
    "attempts",
    "score_positive",
    "manual",
    "no_questions",
    "orphan_answer",
    "no_positive_option",
    "negative_option",
    "basis_all",
    "basis_reached",
    "basis_answered",
    "positive_not_counted",
)
_BASIS_COUNT = {
    ScoreBasis.ALL: "basis_all",
    ScoreBasis.REACHED: "basis_reached",
    ScoreBasis.ANSWERED: "basis_answered",
}


def _scored(us):
    return bool(us.use_score) and us.score is not None


def plan_survey_182(survey_id=SURVEY_182):
    """Submitted attempts on one survey: first or later per (user, survey), scored or not, and
    those whose user is gone, which no first/later count can hold."""
    counts = dict.fromkeys(COUNTS_182, 0)
    first_ids = {us.id for us in _first_attempts() if us.survey_id == survey_id}
    submitted = UserSurvey.objects.filter(survey_id=survey_id, submitted_at__isnull=False).only(
        "id", "user_id", "use_score", "score"
    )
    for us in submitted:
        if us.user_id is None:
            counts["null_user"] += 1
            continue
        when = "first" if us.id in first_ids else "later"
        counts[f"{when}_{'scored' if _scored(us) else 'unscored'}"] += 1
    return {"survey_id": survey_id, **counts}


def plan_max_not_positive():
    """Per survey, the scored first attempts whose basis-aware max is 0 or less."""
    candidates = [us for us in _first_attempts() if _scored(us)]
    maxes = max_scores(candidates)
    attempts = [us for us in candidates if maxes[us.id] <= 0]
    ids = [us.id for us in attempts]

    with_questions = set(UserQuestion.objects.filter(user_survey_id__in=ids).values_list("user_survey_id", flat=True))
    orphaned = set(
        UserAnswer.objects.filter(
            user_survey_id__in=ids, question__isnull=True, selected_options__isnull=False
        ).values_list("user_survey_id", flat=True)
    )
    options = UserAnswerOption.objects.filter(user_survey_id__in=ids)
    positive_on = defaultdict(set)
    for us_id, question_id in options.filter(score__gt=0).values_list("user_survey_id", "schema__question_id"):
        positive_on[us_id].add(question_id)
    positive = set(positive_on)
    negative = set(options.filter(score__lt=0).values_list("user_survey_id", flat=True))

    counted = _questions_counted(attempts)

    surveys = defaultdict(lambda: dict.fromkeys(COUNTS_MAX, 0))
    for us in attempts:
        row = surveys[us.survey_id]
        row["attempts"] += 1
        row["score_positive"] += us.score > 0
        row["manual"] += us.evaluation_type == UserSurvey.EVALUATION_TYPE_MANUAL
        row["no_questions"] += us.id not in with_questions
        row["orphan_answer"] += us.id in orphaned
        row["no_positive_option"] += us.id not in positive
        row["negative_option"] += us.id in negative
        if us.score_basis in _BASIS_COUNT:
            row[_BASIS_COUNT[us.score_basis]] += 1
        row["positive_not_counted"] += bool(positive_on[us.id]) and not positive_on[us.id] & counted[us.id]
    return [{"survey_id": sid, **c} for sid, c in sorted(surveys.items())]


def _questions_counted(attempts):
    """Per attempt, the question ids `max_scores` counts under the attempt's basis
    (`forms:AD-10`): every question for `all`, on-path ones for `reached`, on-path ones with a
    selected option for `answered`. Two queries however many attempts."""
    by_id = {us.id: us for us in attempts}
    answering = [us_id for us_id, us in by_id.items() if us.score_basis == ScoreBasis.ANSWERED]
    answered = set()
    if answering:
        answered = set(
            UserAnswer.objects.filter(user_survey_id__in=answering, selected_options__isnull=False).values_list(
                "user_survey_id", "question_id"
            )
        )
    counted = defaultdict(set)
    for us_id, question_id, on_path in UserQuestion.objects.filter(user_survey_id__in=by_id).values_list(
        "user_survey_id", "id", "on_path"
    ):
        basis = by_id[us_id].score_basis
        if basis != ScoreBasis.ALL and not on_path:
            continue
        if basis == ScoreBasis.ANSWERED and (us_id, question_id) not in answered:
            continue
        counted[us_id].add(question_id)
    return counted


def _join(row, keys):
    return " ".join(f"{key}={row[key]}" for key in keys)


def describe(survey_182, max_not_positive):
    lines = [f"{TAG} first_vs_later survey={survey_182['survey_id']} {_join(survey_182, COUNTS_182)}"]
    totals = dict.fromkeys(COUNTS_MAX, 0)
    for row in max_not_positive:
        lines.append(f"{TAG} max_not_positive survey={row['survey_id']} {_join(row, COUNTS_MAX)}")
        for key in totals:
            totals[key] += row[key]
    lines.append(f"{TAG} max_not_positive summary: surveys={len(max_not_positive)} {_join(totals, COUNTS_MAX)}")
    return lines
