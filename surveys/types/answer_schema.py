from __future__ import annotations

from typing import Annotated, List, Optional

import strawberry
import strawberry_django
from strawberry import auto
from strawberry.types import Info

from pkg_media.integrations.strawberry import EmbeddedMediaType

from media import embedding
from surveys.models import AnswerSchema, AnswerSchemaOption
from .translations import AnswerSchemaOptionTranslationType, AnswerSchemaTranslationType


@strawberry_django.type(AnswerSchema)
class AnswerSchemaType:
    id: auto
    survey_id: auto
    section_id: auto
    question_id: auto
    type: auto
    with_file: auto
    is_mcq: auto
    is_grid: auto
    options: List["AnswerSchemaOptionType"]
    translations: List[AnswerSchemaTranslationType]


@strawberry_django.type(AnswerSchemaOption)
class AnswerSchemaOptionType:
    id: auto
    survey_id: auto
    section_id: auto
    question_id: auto
    schema_id: auto
    text: auto
    score: auto
    classification_id: auto
    classification: Optional[Annotated["ClassificationType", strawberry.lazy("classifications.types.classification")]]
    option_recommendations: List[Annotated["RecommendationType", strawberry.lazy("recommendations.types.recommendation")]]

    @strawberry.field
    def option_recommendations(self) -> List[Annotated["RecommendationType", strawberry.lazy("recommendations.types.recommendation")]]:
        """Soft deletes are excluded, as they are for sections, questions and
        classifications. Without this the admin builder's delete button looked inert:
        `delete_recommendation` stamps `deleted_at` and the next refetch returned the
        row again, so the recommendation reappeared the moment it was removed."""
        return list(self.option_recommendations.filter(deleted_at__isnull=True))
    image_asset_id: auto

    @strawberry_django.field(only=["image_asset_id", "survey_id"], description="The option's image.")
    def media(self, info: Info) -> Optional[EmbeddedMediaType]:
        return embedding.embedded(info, self.image_asset_id, lambda: embedding.survey_asset_ids(self.survey_id))

    is_row: auto
    is_column: auto
    ending_option: auto
    order: auto
    flow_action: str
    flow_target_id: Optional[strawberry.ID]
    translations: List[AnswerSchemaOptionTranslationType]
