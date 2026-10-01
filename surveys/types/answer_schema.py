from __future__ import annotations

from typing import Annotated, List, Optional

import strawberry
import strawberry_django
from strawberry import auto

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
    is_row: auto
    is_column: auto
    ending_option: auto
    order: auto
    translations: List[AnswerSchemaOptionTranslationType]
