from __future__ import annotations

from typing import List

import strawberry_django
from strawberry import auto

from recommendations.models import Recommendation
from .translations import RecommendationTranslationType


@strawberry_django.type(Recommendation)
class RecommendationType:
    id: auto
    survey_id: auto
    option_id: auto
    created_at: auto
    updated_at: auto
    translations: List[RecommendationTranslationType]
