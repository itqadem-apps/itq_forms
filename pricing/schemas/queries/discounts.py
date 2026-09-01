from typing import List, Optional

import strawberry
from strawberry.types import Info

from pricing.models import Discount
from pricing.types import DiscountType
from app.graphql_ids import as_pk


@strawberry.type
class DiscountsQuery:
    @strawberry.field()
    def discounts(
        self,
        info: Info,
        price_id: Optional[strawberry.ID] = None,
    ) -> List[DiscountType]:
        price_id = as_pk(price_id)
        qs = Discount.objects.all()
        if price_id is not None:
            qs = qs.filter(price_id=price_id)
        return list(qs)
