from __future__ import annotations

from typing import List, Optional, Annotated

import strawberry
import strawberry_django
from strawberry import auto

from pricing.models import Price


@strawberry_django.type(Price)
class PriceType:
    id: auto
    survey_id: auto
    collection_id: auto
    currency: auto
    amount_cents: auto
    compare_at_amount_cents: auto

    @strawberry.field
    def discounts(self) -> List[Annotated["DiscountType", strawberry.lazy("pricing.types.discount")]]:
        return list(self.discounts.all())
