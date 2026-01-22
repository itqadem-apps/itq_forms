from __future__ import annotations

from typing import List

import strawberry_django
from strawberry import auto

from surveys.models import Recommendation
from .translations import RecommendationTranslationType


@strawberry_django.type(Recommendation)
class RecommendationType:
    id: auto
    description: auto
    translations: List[RecommendationTranslationType]
