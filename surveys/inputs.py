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
    assessment_type: Optional[str] = None
    display_option: Optional[str] = None
    is_timed: Optional[bool] = None
    assignable_to_user: Optional[bool] = None
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
    content_type_id: Optional[int] = None
    object_id: Optional[int] = None
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
    assessment_type: Optional[str]
    display_option: Optional[str]
    is_timed: Optional[bool]
    assignable_to_user: Optional[bool]
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
    content_type_id: Optional[int]
    object_id: Optional[int]
    q: Optional[str]


@strawberry.enum
class SurveySortField(str, Enum):
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    ID = "id"
    TITLE = "title"
    DESCRIPTION = "description"
    SHORT_DESCRIPTION = "short_description"
    SLUG = "slug"
    LANGUAGE = "language"
    STATUS = "status"
    ASSESSMENT_TYPE = "assessment_type"
    DISPLAY_OPTION = "display_option"
    IS_TIMED = "is_timed"
    ASSIGNABLE_TO_USER = "assignable_to_user"
    IS_EVALUABLE = "is_evaluable"
    EVALUATION_TYPE = "evaluation_type"
    USE_SCORE = "use_score"
    USE_CLASSIFICATIONS = "use_classifications"
    USE_RECOMMENDATIONS = "use_recommendations"
    USE_ACTIONS = "use_actions"
    ALLOW_END_BASED_ON_ANSWER_REPEAT = "allow_end_based_on_answer_repeat"
    ANSWERS_COUNT_TO_END = "answers_count_to_end"
    END_BASED_ON_ANSWER_REPEAT_IN_ROW = "end_based_on_answer_repeat_in_row"
    ALLOW_UPDATE_ANSWER_OPTIONS_SCORES_BASED_ON_CLASSIFICATION = (
        "allow_update_answer_options_scores_based_on_classification"
    )
    ALLOW_UPDATE_ANSWER_OPTIONS_TEXT_BASED_ON_CLASSIFICATION = (
        "allow_update_answer_options_text_based_on_classification"
    )
    CREATE_OPTION_FOR_EACH_CLASSIFICATION = "create_option_for_each_classification"
    CONTENT_TYPE_ID = "content_type_id"
    OBJECT_ID = "object_id"


@strawberry.input
class SurveySortFieldInput:
    field: SurveySortField
    direction: SortDirection = SortDirection.ASC


@strawberry.input
class SurveySortInput:
    fields: List[SurveySortFieldInput]


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
    author_id: Optional[str]
    q: Optional[str]


@strawberry.enum
class SurveyCollectionSortField(str, Enum):
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    ID = "id"
    STATUS = "status"
    PRIVACY_STATUS = "privacy_status"
    TITLE = "title"
    DESCRIPTION = "description"
    SHORT_DESCRIPTION = "short_description"
    SLUG = "slug"
    LANGUAGE = "language"
    CATEGORY_ID = "category_id"
    SPONSOR = "sponsor"
    TYPE = "type"
    AUTHOR_ID = "author_id"


@strawberry.input
class SurveyCollectionSortFieldInput:
    field: SurveyCollectionSortField
    direction: SortDirection = SortDirection.ASC


@strawberry.input
class SurveyCollectionSortInput:
    fields: List[SurveyCollectionSortFieldInput]


@strawberry.input
class SurveyCollectionsListInput:
    limit: int = 20
    offset: int = 0
    filters: Optional[SurveyCollectionFiltersInput] = None
    sort: Optional[SurveyCollectionSortInput] = None


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
