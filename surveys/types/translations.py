from __future__ import annotations

import strawberry_django
from strawberry import auto

from surveys.models import (
    AnswerSchemaOptionTranslation,
    AnswerSchemaTranslation,
    QuestionTranslation,
    SectionTranslation,
    SurveyTranslation,
)
from taxonomy.models import CategoryTranslation


@strawberry_django.type(CategoryTranslation)
class CategoryTranslationType:
    id: auto
    language: auto
    name: auto
    slug: auto


@strawberry_django.type(SurveyTranslation)
class SurveyTranslationType:
    id: auto
    language: auto
    title: auto
    description: auto
    short_description: auto
    slug: auto


@strawberry_django.type(SectionTranslation)
class SectionTranslationType:
    id: auto
    language: auto
    title: auto
    description: auto


@strawberry_django.type(QuestionTranslation)
class QuestionTranslationType:
    id: auto
    language: auto
    title: auto
    description: auto


@strawberry_django.type(AnswerSchemaTranslation)
class AnswerSchemaTranslationType:
    id: auto
    language: auto


@strawberry_django.type(AnswerSchemaOptionTranslation)
class AnswerSchemaOptionTranslationType:
    id: auto
    language: auto
    text: auto


from classifications.types import ClassificationTranslationType  # noqa: F401
from recommendations.types import ActionTranslationType, RecommendationTranslationType  # noqa: F401
