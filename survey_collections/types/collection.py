from __future__ import annotations

from typing import Annotated, List

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
    assessments: List[Annotated["SurveyType", strawberry.lazy("surveys.types.survey")]]

    @strawberry.field
    def assessments(self) -> List[Annotated["SurveyType", strawberry.lazy("surveys.types.survey")]]:
        return list(self.assessments.filter(deleted_at__isnull=True))


@strawberry_django.type(SurveyCollectionTranslation)
class SurveyCollectionTranslationType:
    id: auto
    language: auto
    title: auto
    description: auto
    short_description: auto
    slug: auto
    seo: auto
