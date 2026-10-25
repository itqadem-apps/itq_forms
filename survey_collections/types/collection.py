from __future__ import annotations

from typing import Annotated, List, Optional

import strawberry
import strawberry_django
from strawberry import auto
from strawberry.types import Info

from pkg_media.integrations.strawberry import EmbeddedMediaType

from media import embedding
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
    cover_id: auto
    thumb_id: auto
    translations: List["SurveyCollectionTranslationType"]
    prices: List[PriceType]
    assessments: List[Annotated["SurveyType", strawberry.lazy("surveys.types.survey")]]

    @strawberry_django.field(only=["thumb_id", "cover_id"], description="Card artwork: the thumb, else the cover.")
    def thumb(self, info: Info) -> Optional[EmbeddedMediaType]:
        return embedding.embedded(info, embedding.thumb_id(self), lambda: (self.thumb_id, self.cover_id))

    @strawberry_django.field(only=["thumb_id", "cover_id"], description="Hero artwork and the share image: the cover, else the thumb.")
    def cover(self, info: Info) -> Optional[EmbeddedMediaType]:
        return embedding.embedded(info, embedding.cover_id(self), lambda: (self.thumb_id, self.cover_id))

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
