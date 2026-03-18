from __future__ import annotations

from typing import List

import strawberry_django
from strawberry import auto

from survey_collections.models import SurveyCollection, SurveyCollectionTranslation
from pricing.types import PriceType


@strawberry_django.type(SurveyCollection)
class SurveyCollectionType:
    id: auto
    status: auto
    title: auto
    description: auto
    short_description: auto
    slug: auto
    language: auto
    created_at: auto
    updated_at: auto
    deleted_at: auto
    category_id: auto
    sponsor: auto
    type: auto
    translations: List["SurveyCollectionTranslationType"]
    prices: List[PriceType]


@strawberry_django.type(SurveyCollectionTranslation)
class SurveyCollectionTranslationType:
    id: auto
    language: auto
    title: auto
    description: auto
    short_description: auto
    slug: auto
