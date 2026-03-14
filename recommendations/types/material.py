from __future__ import annotations

import strawberry_django
from strawberry import auto

from recommendations.models import Material
from .recommendable import RecommendableType


@strawberry_django.type(Material)
class MaterialType:
    id: auto
    action_id: auto
    recommendable: RecommendableType
