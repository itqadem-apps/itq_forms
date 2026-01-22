from __future__ import annotations

import strawberry_django
from strawberry import auto

from surveys.models import (
    ActionTranslation,
    AnswerSchemaOptionTranslation,
    AnswerSchemaTranslation,
    ClassificationTranslation,
    QuestionTranslation,
    RecommendationTranslation,
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


@strawberry_django.type(ActionTranslation)
class ActionTranslationType:
    id: auto
    language: auto
    title: auto
    description: auto


@strawberry_django.type(RecommendationTranslation)
class RecommendationTranslationType:
    id: auto
    language: auto
    description: auto


@strawberry_django.type(ClassificationTranslation)
class ClassificationTranslationType:
    id: auto
    language: auto
    name: auto
