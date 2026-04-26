from dataclasses import dataclass
from enum import Enum
from typing import Optional

import strawberry
from pkg_filters.integrations.strawberry import (
    DateTimeRangeFilterInput,
    SortDirection,
)


@strawberry.input
class UserSurveyFiltersInput:
    id: Optional[int] = None
    survey_id: Optional[int] = None
    survey_type: Optional[str] = None
    collection_id: Optional[int] = None
    collection_type: Optional[str] = None
    child_id: Optional[str] = None
    submitted: Optional[bool] = None
    submitted_at: Optional[DateTimeRangeFilterInput] = None
    evaluated_at: Optional[DateTimeRangeFilterInput] = None


@dataclass(frozen=True)
class UserSurveyFilters:
    id: Optional[int]
    survey_id: Optional[int]
    survey_type: Optional[str]
    collection_id: Optional[int]
    collection_type: Optional[str]
    child_id: Optional[str]
    submitted: Optional[bool]
    submitted_at: Optional[object]  # RangeFilterVO[datetime]
    evaluated_at: Optional[object]  # RangeFilterVO[datetime]


@strawberry.input
class UserSurveysListInput:
    limit: int = 20
    offset: int = 0
    filters: Optional[UserSurveyFiltersInput] = None
    sort: Optional["UserSurveySortInput"] = None


@strawberry.enum
class UserSurveySortField(str, Enum):
    ID = "id"
    SUBMITTED_AT = "submitted_at"
    EVALUATED_AT = "evaluated_at"
    SCORE = "score"


@strawberry.input
class UserSurveySortInput:
    id: Optional[SortDirection] = None
    submitted_at: Optional[SortDirection] = None
    evaluated_at: Optional[SortDirection] = None
    score: Optional[SortDirection] = None
