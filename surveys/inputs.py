from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

import strawberry
import strawberry_django
from strawberry import UNSET
from pkg_filters.integrations.strawberry import (
    DateTimeRangeFilterInput,
    IntRangeFilterInput,
    SortDirection,
)

from external_references.inputs import ExternalReferenceFilterInput, ExternalReferenceInput
from pricing.inputs import PriceNestedInput


@strawberry.input
class SurveyFiltersInput:
    created_at: Optional[DateTimeRangeFilterInput] = None
    updated_at: Optional[DateTimeRangeFilterInput] = None
    id: Optional[strawberry.ID] = None
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
    slug: Optional[str] = None
    category_id: Optional[str] = None
    price: Optional[IntRangeFilterInput] = None
    has_discount: Optional[bool] = None
    is_free: Optional[bool] = None
    currency: Optional[str] = None
    collection_id: Optional[strawberry.ID] = None
    external_reference: Optional[ExternalReferenceFilterInput] = None
    q: Optional[str] = None


@dataclass(frozen=True)
class SurveyFilters:
    created_at: Optional[object]  # RangeFilterVO[datetime]
    updated_at: Optional[object]  # RangeFilterVO[datetime]
    id: Optional[int]
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
    slug: Optional[str]
    category_id: Optional[str]
    price: Optional[object]
    has_discount: Optional[bool]
    is_free: Optional[bool]
    currency: Optional[str]
    collection_id: Optional[int]
    q: Optional[str]


@strawberry.enum
class SurveySortField(str, Enum):
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


@strawberry.input
class SurveySortInput:
    created_at: Optional[SortDirection] = None
    updated_at: Optional[SortDirection] = None


@strawberry.input
class SurveysListInput:
    limit: int = 20
    offset: int = 0
    filters: Optional[SurveyFiltersInput] = None
    sort: Optional[SurveySortInput] = None


@strawberry.input
class QuestionsFiltersInput:
    question_ids: Optional[List[int]] = None
    section_id: Optional[strawberry.ID] = None
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


# ==================== CRUD INPUT TYPES ====================

# Translation Inputs
@strawberry.input
class TranslationInput:
    language: str
    title: Optional[str] = None
    description: Optional[str] = None


@strawberry.input
class SurveyTranslationInput:
    language: str
    title: Optional[str] = None
    description: Optional[str] = None
    short_description: Optional[str] = None
    slug: Optional[str] = None
    seo: Optional[strawberry.scalars.JSON] = None


@strawberry.input
class SectionTranslationInput:
    language: str
    title: Optional[str] = None
    description: Optional[str] = None


@strawberry.input
class QuestionTranslationInput:
    language: str
    title: Optional[str] = None
    description: Optional[str] = None


@strawberry.input
class AnswerSchemaOptionTranslationInput:
    language: str
    text: Optional[str] = None


from classifications.inputs import ClassificationTranslationInput, ClassificationInput  # noqa: F401
from recommendations.inputs import RecommendationTranslationInput, ActionTranslationInput, RecommendationInput, ActionInput  # noqa: F401


# Survey Inputs
from surveys.models import Survey, SurveyTranslation


@strawberry_django.input(SurveyTranslation, exclude=["id", "survey"])
class SurveyTranslationCreateInput:
    pass  # auto: language (required), title, description, short_description, slug


@strawberry_django.partial(SurveyTranslation, exclude=["survey"])
class SurveyTranslationUpdateInput:
    pass  # auto (all optional): id, language, title, description, short_description, slug


@strawberry_django.input(Survey, exclude=["status", "category", "created_at", "updated_at", "time_limit"])
class SurveyCreateInput:
    # Manual fields that cannot use auto:
    category_id: Optional[str] = UNSET
    time_limit: Optional[str] = UNSET
    translations: Optional[List[SurveyTranslationCreateInput]] = UNSET
    external_reference: Optional[ExternalReferenceInput] = UNSET
    prices: Optional[List[PriceNestedInput]] = UNSET


@strawberry_django.partial(Survey, exclude=["status", "category", "created_at", "updated_at", "time_limit"])
class SurveyUpdateInput:
    # id is required for update (overrides auto-optional behavior)
    id: int
    # Manual fields that cannot use auto:
    category_id: Optional[str] = UNSET
    time_limit: Optional[str] = UNSET
    translations: Optional[List[SurveyTranslationUpdateInput]] = UNSET
    prices: Optional[List[PriceNestedInput]] = UNSET


# Section Inputs
@strawberry.input
class SectionInput:
    title: Optional[str] = UNSET
    description: Optional[str] = UNSET
    order: Optional[int] = UNSET
    is_hidden: Optional[bool] = UNSET
    cover_asset_id: Optional[str] = UNSET
    submit_action: Optional[str] = UNSET
    submit_action_target_id: Optional[int] = UNSET
    translations: Optional[List[SectionTranslationInput]] = UNSET


# Question Inputs
@strawberry.input
class QuestionInput:
    title: Optional[str] = UNSET
    description: Optional[str] = UNSET
    answer_time: Optional[str] = UNSET
    order: Optional[int] = UNSET
    is_required: Optional[bool] = UNSET
    type: Optional[str] = UNSET
    cover_asset_id: Optional[str] = UNSET
    translations: Optional[List[QuestionTranslationInput]] = UNSET


# Answer Schema Inputs
@strawberry.input
class AnswerSchemaOptionInput:
    text: Optional[str] = UNSET
    score: Optional[int] = UNSET
    classification_id: Optional[int] = UNSET
    image_asset_id: Optional[str] = UNSET
    is_row: Optional[bool] = UNSET
    is_column: Optional[bool] = UNSET
    ending_option: Optional[bool] = UNSET
    order: Optional[int] = UNSET
    translations: Optional[List[AnswerSchemaOptionTranslationInput]] = UNSET


@strawberry.input
class AnswerSchemaInput:
    type: Optional[str] = UNSET
    with_file: Optional[bool] = UNSET
    is_mcq: Optional[bool] = UNSET
    is_grid: Optional[bool] = UNSET


# Nested/Bulk Inputs
@strawberry.input
class AnswerSchemaOptionNestedInput:
    text: Optional[str] = None
    score: Optional[int] = None
    classification_id: Optional[int] = None
    image_asset_id: Optional[str] = None
    is_row: Optional[bool] = None
    is_column: Optional[bool] = None
    ending_option: Optional[bool] = None
    order: Optional[int] = None


@strawberry.input
class QuestionNestedInput:
    title: Optional[str] = None
    description: Optional[str] = None
    answer_time: Optional[str] = None
    order: Optional[int] = None
    is_required: Optional[bool] = None
    type: Optional[str] = None
    cover_asset_id: Optional[str] = None
    options: Optional[List[AnswerSchemaOptionNestedInput]] = None


@strawberry.input
class SectionNestedInput:
    title: Optional[str] = None
    description: Optional[str] = None
    order: Optional[int] = None
    is_hidden: Optional[bool] = None
    cover_asset_id: Optional[str] = None
    questions: Optional[List[QuestionNestedInput]] = None
