from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

import strawberry
from pkg_filters.integrations.strawberry import (
    DateTimeRangeFilterInput,
    SortDirection,
)


@strawberry.input
class SurveyFiltersInput:
    created_at: Optional[DateTimeRangeFilterInput] = None
    updated_at: Optional[DateTimeRangeFilterInput] = None
    id: Optional[int] = None
    title: Optional[str] = None
    description: Optional[str] = None
    short_description: Optional[str] = None
    slug: Optional[str] = None
    language: Optional[str] = None
    status: Optional[str] = None
    survey_type: Optional[str] = None
    display_option: Optional[str] = None
    is_timed: Optional[bool] = None
    is_for_child: Optional[bool] = None
    is_evaluable: Optional[bool] = None
    evaluation_type: Optional[str] = None
    use_score: Optional[bool] = None
    use_classifications: Optional[bool] = None
    use_recommendations: Optional[bool] = None
    use_actions: Optional[bool] = None
    allow_end_based_on_answer_repeat: Optional[bool] = None
    answers_count_to_end: Optional[int] = None
    end_based_on_answer_repeat_in_row: Optional[bool] = None
    allow_update_answer_options_scores_based_on_classification: Optional[bool] = None
    allow_update_answer_options_text_based_on_classification: Optional[bool] = None
    create_option_for_each_classification: Optional[bool] = None
    price_min_cents: Optional[int] = None
    price_max_cents: Optional[int] = None
    has_discount: Optional[bool] = None
    is_free: Optional[bool] = None
    currency: Optional[str] = None
    q: Optional[str] = None


@dataclass(frozen=True)
class SurveyFilters:
    created_at: Optional[object]  # RangeFilterVO[datetime]
    updated_at: Optional[object]  # RangeFilterVO[datetime]
    id: Optional[int]
    title: Optional[str]
    description: Optional[str]
    short_description: Optional[str]
    slug: Optional[str]
    language: Optional[str]
    status: Optional[str]
    survey_type: Optional[str]
    display_option: Optional[str]
    is_timed: Optional[bool]
    is_for_child: Optional[bool]
    is_evaluable: Optional[bool]
    evaluation_type: Optional[str]
    use_score: Optional[bool]
    use_classifications: Optional[bool]
    use_recommendations: Optional[bool]
    use_actions: Optional[bool]
    allow_end_based_on_answer_repeat: Optional[bool]
    answers_count_to_end: Optional[int]
    end_based_on_answer_repeat_in_row: Optional[bool]
    allow_update_answer_options_scores_based_on_classification: Optional[bool]
    allow_update_answer_options_text_based_on_classification: Optional[bool]
    create_option_for_each_classification: Optional[bool]
    price_min_cents: Optional[int]
    price_max_cents: Optional[int]
    has_discount: Optional[bool]
    is_free: Optional[bool]
    currency: Optional[str]
    q: Optional[str]


@strawberry.enum
class SurveySortField(str, Enum):
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    TITLE = "title"
    PRICE = "price"


@strawberry.input
class SurveySortInput:
    created_at: Optional[SortDirection] = None
    updated_at: Optional[SortDirection] = None
    title: Optional[SortDirection] = None
    price: Optional[SortDirection] = None


@strawberry.input
class SurveysListInput:
    limit: int = 20
    offset: int = 0
    filters: Optional[SurveyFiltersInput] = None
    sort: Optional[SurveySortInput] = None


@strawberry.input
class SurveyCollectionFiltersInput:
    created_at: Optional[DateTimeRangeFilterInput] = None
    updated_at: Optional[DateTimeRangeFilterInput] = None
    id: Optional[int] = None
    status: Optional[str] = None
    privacy_status: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    short_description: Optional[str] = None
    slug: Optional[str] = None
    language: Optional[str] = None
    category_id: Optional[str] = None
    sponsor: Optional[int] = None
    type: Optional[str] = None
    author_id: Optional[str] = None
    q: Optional[str] = None


@dataclass(frozen=True)
class SurveyCollectionFilters:
    created_at: Optional[object]  # RangeFilterVO[datetime]
    updated_at: Optional[object]  # RangeFilterVO[datetime]
    id: Optional[int]
    status: Optional[str]
    privacy_status: Optional[str]
    title: Optional[str]
    description: Optional[str]
    short_description: Optional[str]
    slug: Optional[str]
    language: Optional[str]
    category_id: Optional[str]
    sponsor: Optional[int]
    type: Optional[str]
    q: Optional[str]


@strawberry.enum
class SurveyCollectionSortField(str, Enum):
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    TITLE = "title"
    PRICE = "price"


@strawberry.input
class SurveyCollectionSortInput:
    created_at: Optional[SortDirection] = None
    updated_at: Optional[SortDirection] = None
    title: Optional[SortDirection] = None
    price: Optional[SortDirection] = None


@strawberry.input
class SurveyCollectionsListInput:
    limit: int = 20
    offset: int = 0
    filters: Optional[SurveyCollectionFiltersInput] = None
    sort: Optional[SurveyCollectionSortInput] = None


@strawberry.input
class UserSurveyFiltersInput:
    survey_id: Optional[int] = None
    survey_type: Optional[str] = None
    collection_id: Optional[int] = None
    collection_type: Optional[str] = None
    child_id: Optional[str] = None
    is_paid: Optional[bool] = None
    submitted: Optional[bool] = None
    submitted_at: Optional[DateTimeRangeFilterInput] = None
    evaluated_at: Optional[DateTimeRangeFilterInput] = None


@dataclass(frozen=True)
class UserSurveyFilters:
    survey_id: Optional[int]
    survey_type: Optional[str]
    collection_id: Optional[int]
    collection_type: Optional[str]
    child_id: Optional[str]
    is_paid: Optional[bool]
    submitted: Optional[bool]
    submitted_at: Optional[object]  # RangeFilterVO[datetime]
    evaluated_at: Optional[object]  # RangeFilterVO[datetime]


@strawberry.input
class UserSurveysListInput:
    limit: int = 20
    offset: int = 0
    filters: Optional[UserSurveyFiltersInput] = None


@strawberry.input
class QuestionsFiltersInput:
    question_ids: Optional[List[int]] = None
    section_id: Optional[int] = None
    is_required: Optional[bool] = None
    question_type: Optional[str] = None
    answered: Optional[bool] = None


@dataclass(frozen=True)
class QuestionsFilters:
    question_ids: Optional[List[int]]
    section_id: Optional[int]
    is_required: Optional[bool]
    question_type: Optional[str]
    answered: Optional[bool]
