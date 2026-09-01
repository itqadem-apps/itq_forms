from typing import List, Optional

import strawberry
from strawberry.types import Info

from recommendations.models import Recommendable
from recommendations.types import RecommendableType
from app.graphql_ids import as_pk


@strawberry.type
class RecommendablesQuery:
    @strawberry.field()
    def recommendable(self, info: Info, id: strawberry.ID) -> Optional[RecommendableType]:
        id = as_pk(id)
        try:
            return Recommendable.objects.get(pk=id)
        except Recommendable.DoesNotExist:
            return None

    @strawberry.field()
    def recommendables(self, info: Info) -> List[RecommendableType]:
        return Recommendable.objects.all()
