from typing import List, Optional

import strawberry
from strawberry.types import Info

from pricing.models import Discount
from pricing.types import DiscountType


@strawberry.type
class DiscountsQuery:
    @strawberry.field()
    def discounts(
        self,
        info: Info,
        price_id: Optional[int] = None,
    ) -> List[DiscountType]:
        qs = Discount.objects.all()
        if price_id is not None:
            qs = qs.filter(price_id=price_id)
        return list(qs)
