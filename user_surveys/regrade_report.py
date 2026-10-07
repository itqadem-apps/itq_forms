"""What regrading exam grades as score / max_score would change (`forms:AD-10`).

Report half of `estate:AD-20` / `forms:AD-14`. Before v0.0.106 courses stored an exam lesson's
grade as the attempt's raw points clamped to 0..100, and only forms knows the denominator. The
attempt courses recorded is the learner's first submitted attempt per survey, scored or not (first
submission wins there). It is a candidate only when it is scored, judged against `max_scores`, the
basis-aware denominator; a first attempt without a score is counted as `first_unscored` instead.

`plan()` only reads; `describe()` renders it as deploy-log lines. Per-survey counts only: no user,
attempt id, score or grade reaches the log. The apply, a regrade event courses consumes, ships in
its own release.
"""

from collections import defaultdict

from user_surveys.models import UserSurvey
from user_surveys.services import max_scores

TAG = "exam_regrade_report"
_EPSILON = 1e-9
COUNTS = ("candidates", "changed", "over_100", "max_not_positive", "first_unscored", "manual_evaluated")


def _clamp(value):
    return min(100.0, max(0.0, float(value)))


def grades(score, max_):
    """(old, new) grade for one attempt: the clamped raw score, and score / max as a percentage
    falling back to the old grade when max is not positive, as courses does."""
    old = _clamp(score)
    new = _clamp(score / max_ * 100) if max_ > 0 else old
    return old, new


def _first_attempts():
    """Each learner's first submitted attempt per survey, earliest `submitted_at` then id, scored
    or not: courses kept the first submission whatever it carried."""
    first = {}
    attempts = (
        UserSurvey.objects.filter(submitted_at__isnull=False, user__isnull=False, survey__isnull=False)
        .order_by("submitted_at", "id")
        .only("id", "user_id", "survey_id", "score", "score_basis", "use_score", "evaluation_type")
    )
    for us in attempts:
        first.setdefault((us.user_id, us.survey_id), us)
    return list(first.values())


def plan():
    """Per-survey counts over the first attempts, read and never written. A first attempt with
    no score is not a candidate: courses stored 100 for it, and there is nothing to regrade."""
    surveys = defaultdict(lambda: dict.fromkeys(COUNTS, 0))
    candidates = []
    for us in _first_attempts():
        if us.use_score and us.score is not None:
            candidates.append(us)
        else:
            surveys[us.survey_id]["first_unscored"] += 1
    maxes = max_scores(candidates)
    for us in candidates:
        row = surveys[us.survey_id]
        max_ = maxes[us.id]
        old, new = grades(us.score, max_)
        row["candidates"] += 1
        row["changed"] += abs(new - old) > _EPSILON
        row["over_100"] += us.score > 100
        row["max_not_positive"] += max_ <= 0
        # Courses stored 100 for these (the score was null at submit), so the clamped score
        # above is not what courses holds; counted so the apply can treat them on their own.
        row["manual_evaluated"] += us.evaluation_type == UserSurvey.EVALUATION_TYPE_MANUAL
    # A survey line only where there is a candidate (the spec); `first_unscored` on a survey
    # without one still reaches the summary.
    return {
        "surveys": [{"survey_id": sid, **c} for sid, c in sorted(surveys.items()) if c["candidates"]],
        "first_unscored": sum(c["first_unscored"] for c in surveys.values()),
    }


def _counts(row):
    return (
        f"candidates={row['candidates']} changed={row['changed']} score_over_100={row['over_100']}"
        f" max_not_positive={row['max_not_positive']} first_unscored={row['first_unscored']}"
        f" manual_evaluated={row['manual_evaluated']}"
    )


def describe(p):
    lines = []
    totals = dict.fromkeys(COUNTS, 0)
    for row in p["surveys"]:
        lines.append(f"{TAG} survey={row['survey_id']} {_counts(row)}")
        for key in totals:
            totals[key] += row[key]
    totals["first_unscored"] = p["first_unscored"]
    lines.append(f"{TAG} summary: surveys={len(p['surveys'])} {_counts(totals)}")
    return lines
