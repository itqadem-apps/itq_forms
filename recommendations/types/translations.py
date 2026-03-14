from __future__ import annotations

import strawberry_django
from strawberry import auto

from recommendations.models import ActionTranslation, RecommendationTranslation


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
