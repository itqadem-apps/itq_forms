from typing import List, Optional

import strawberry
from strawberry.types import Info

from pricing.models import Price
from pricing.types import PriceType
from app.graphql_ids import as_pk


@strawberry.type
class PricesQuery:
    @strawberry.field()
    def prices(
        self,
        info: Info,
        survey_id: Optional[strawberry.ID] = None,
        collection_id: Optional[strawberry.ID] = None,
    ) -> List[PriceType]:
        survey_id = as_pk(survey_id)
        collection_id = as_pk(collection_id)
        qs = Price.objects.all()
        if survey_id is not None:
            qs = qs.filter(survey_id=survey_id)
        if collection_id is not None:
            qs = qs.filter(collection_id=collection_id)
        return list(qs)
