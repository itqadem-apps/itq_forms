from __future__ import annotations

from typing import List

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
    image_asset_id: auto
    is_row: auto
    is_column: auto
    ending_option: auto
    order: auto
    translations: List[AnswerSchemaOptionTranslationType]
