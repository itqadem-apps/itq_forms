from __future__ import annotations

from typing import List, Optional

import strawberry
import strawberry_django
from strawberry import auto

from survey_collections.models import SurveyCollection, SurveyCollectionTranslation
from pricing.types import PriceType


@strawberry_django.type(SurveyCollection)
class SurveyCollectionType:
    id: auto
    status: auto
    created_at: auto
    updated_at: auto
    deleted_at: auto
    category_id: auto
    sponsor: auto
    type: auto
    translations: List["SurveyCollectionTranslationType"]
    prices: List[PriceType]

    @strawberry.field
    def title(self) -> Optional[str]:
        t = self.translations.first()
        return t.title if t else None

    @strawberry.field
    def description(self) -> Optional[str]:
        t = self.translations.first()
        return t.description if t else None

    @strawberry.field
    def short_description(self) -> Optional[str]:
        t = self.translations.first()
        return t.short_description if t else None

    @strawberry.field
    def slug(self) -> Optional[str]:
        t = self.translations.first()
        return t.slug if t else None

    @strawberry.field
    def language(self) -> Optional[str]:
        t = self.translations.first()
        return t.language if t else None


@strawberry_django.type(SurveyCollectionTranslation)
class SurveyCollectionTranslationType:
    id: auto
    language: auto
    title: auto
    description: auto
    short_description: auto
    slug: auto
