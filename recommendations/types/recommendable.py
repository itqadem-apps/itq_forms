from __future__ import annotations

from typing import Optional

import strawberry
import strawberry_django
from strawberry import auto

from recommendations import catalog
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

    @strawberry.field()
    def title(self, language: Optional[str] = None) -> Optional[str]:
        return catalog.shown_title(self.data, language)
