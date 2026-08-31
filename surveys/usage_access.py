from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from surveys.models import Usage


FREE_ATTEMPTS = 10


@dataclass(frozen=True)
class UsageSummary:
    total_used: int
    total_limit: int
    has_any: bool
    has_unlimited: bool


def summarize_usage_rows(usages: Iterable[Usage]) -> UsageSummary:
    rows = list(usages)
    has_any = bool(rows)
    has_unlimited = any((row.usage_limit or 0) == 0 for row in rows)
    total_used = sum(int(row.used_count or 0) for row in rows)
    total_limit = 0 if has_unlimited else sum(int(row.usage_limit or 0) for row in rows)
    return UsageSummary(
        total_used=total_used,
        total_limit=total_limit,
        has_any=has_any,
        has_unlimited=has_unlimited,
    )


def select_usage_to_consume(usages: Iterable[Usage]) -> Usage | None:
    for row in usages:
        if (row.usage_limit or 0) == 0 or row.used_count < row.usage_limit:
            return row
    return None


_ANY_CHILD = object()


def count_free_attempts_used(*, user_id, survey_id, child_id=_ANY_CHILD) -> int:
    """Free-tier attempts consumed: submitted ``UserSurvey`` snapshots.

    On the free tier no ``Usage`` row is ever written (see
    ``enroll_assessment``), so the only record that an attempt was spent is the
    submitted snapshot itself. Pass ``child_id`` to scope the count the way the
    enrolment gate does — each child carries their own allowance; omit it to
    count every attempt on the survey regardless of who it was for.
    """
    from user_surveys.models import UserSurvey

    queryset = UserSurvey.objects.filter(
        user_id=user_id, survey_id=survey_id, submitted_at__isnull=False
    )
    if child_id is not _ANY_CHILD:
        queryset = queryset.filter(child_id=child_id)
    return queryset.count()


def resolve_usage_used(*, user_id, survey_id, child_id=_ANY_CHILD) -> int:
    """The one answer to "how many attempts has this user spent?".

    Paid usage rows win when they exist; otherwise we fall back to the free-tier
    count. Every surface that reports the number goes through here so the survey
    list, the attempt, and the enrolment gate cannot drift apart.
    """
    usages = _usage_rows(user_id=user_id, survey_id=survey_id)
    summary = summarize_usage_rows(usages)
    if summary.has_any:
        return summary.total_used
    return count_free_attempts_used(
        user_id=user_id, survey_id=survey_id, child_id=child_id
    )


def resolve_usage_limit(*, user_id, survey_id) -> int:
    """The allowance matching :func:`resolve_usage_used` — never 0 for a user
    who simply has no usage rows; that user is on the free tier."""
    summary = summarize_usage_rows(_usage_rows(user_id=user_id, survey_id=survey_id))
    if not summary.has_any:
        return FREE_ATTEMPTS
    return summary.total_limit or FREE_ATTEMPTS


def _usage_rows(*, user_id, survey_id) -> list[Usage]:
    return list(
        Usage.objects.filter(user_id=user_id, survey_id=survey_id).order_by(
            "created_at", "id"
        )
    )
