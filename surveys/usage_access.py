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
