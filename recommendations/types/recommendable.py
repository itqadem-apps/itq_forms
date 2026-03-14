from __future__ import annotations

import strawberry_django
from strawberry import auto

from recommendations.models import Recommendable


@strawberry_django.type(Recommendable)
class RecommendableType:
    id: auto
    source_service: auto
    source_model: auto
    source_id: auto
    data: auto
    created_at: auto
    updated_at: auto
