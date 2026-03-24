from typing import List, Optional

import strawberry
from strawberry.types import Info

from pricing.models import Price
from pricing.types import PriceType


@strawberry.type
class PricesQuery:
    @strawberry.field()
    def prices(
        self,
        info: Info,
        survey_id: Optional[int] = None,
        collection_id: Optional[int] = None,
    ) -> List[PriceType]:
        qs = Price.objects.all()
        if survey_id is not None:
            qs = qs.filter(survey_id=survey_id)
        if collection_id is not None:
            qs = qs.filter(collection_id=collection_id)
        return list(qs)
