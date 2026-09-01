from typing import List, Optional

import strawberry
from strawberry.types import Info

from recommendations.models import Material
from recommendations.types import MaterialType
from app.graphql_ids import as_pk


@strawberry.type
class MaterialsQuery:
    @strawberry.field()
    def material(self, info: Info, id: strawberry.ID) -> Optional[MaterialType]:
        id = as_pk(id)
        try:
            return Material.objects.get(pk=id)
        except Material.DoesNotExist:
            return None

    @strawberry.field()
    def materials(self, info: Info, action_id: strawberry.ID) -> List[MaterialType]:
        action_id = as_pk(action_id)
        return Material.objects.filter(action_id=action_id)
