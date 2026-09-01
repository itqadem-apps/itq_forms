from dataclasses import dataclass
from typing import List, Optional

import strawberry
from strawberry import UNSET
from pkg_filters.integrations.strawberry import (
    DateTimeRangeFilterInput,
    IntRangeFilterInput,
    SortDirection,
)

from enum import Enum

from external_references.inputs import ExternalReferenceFilterInput
from pricing.inputs import PriceNestedInput


@strawberry.input
class SurveyCollectionFiltersInput:
    created_at: Optional[DateTimeRangeFilterInput] = None
    updated_at: Optional[DateTimeRangeFilterInput] = None
    id: Optional[strawberry.ID] = None
    status: Optional[str] = None
    title: Optional[str] = None
    slug: Optional[str] = None
    language: Optional[str] = None
    category_id: Optional[str] = None
    sponsor: Optional[int] = None
    type: Optional[str] = None
    price: Optional[IntRangeFilterInput] = None
    has_discount: Optional[bool] = None
    is_free: Optional[bool] = None
    currency: Optional[str] = None
    external_reference: Optional[ExternalReferenceFilterInput] = None
    q: Optional[str] = None


@dataclass(frozen=True)
class SurveyCollectionFilters:
    created_at: Optional[object]  # RangeFilterVO[datetime]
    updated_at: Optional[object]  # RangeFilterVO[datetime]
    id: Optional[int]
    status: Optional[str]
    title: Optional[str]
    slug: Optional[str]
    language: Optional[str]
    category_id: Optional[str]
    sponsor: Optional[int]
    type: Optional[str]
    price: Optional[object]
    has_discount: Optional[bool]
    is_free: Optional[bool]
    currency: Optional[str]
    q: Optional[str]


@strawberry.enum
class SurveyCollectionSortField(str, Enum):
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    TITLE = "title"


@strawberry.input
class SurveyCollectionSortInput:
    created_at: Optional[SortDirection] = None
    updated_at: Optional[SortDirection] = None
    title: Optional[SortDirection] = None


@strawberry.input
class SurveyCollectionsListInput:
    limit: int = 20
    offset: int = 0
    filters: Optional[SurveyCollectionFiltersInput] = None
    sort: Optional[SurveyCollectionSortInput] = None


@strawberry.input
class SurveyCollectionTranslationInput:
    language: str
    title: Optional[str] = None
    description: Optional[str] = None
    short_description: Optional[str] = None
    slug: Optional[str] = None
    seo: Optional[strawberry.scalars.JSON] = None


@strawberry.input
class SurveyCollectionInput:
    status: Optional[str] = UNSET
    category_id: Optional[str] = UNSET
    sponsor: Optional[int] = UNSET
    type: Optional[str] = UNSET
    translations: Optional[List[SurveyCollectionTranslationInput]] = UNSET
    prices: Optional[List[PriceNestedInput]] = UNSET
