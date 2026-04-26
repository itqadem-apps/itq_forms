from typing import List, Optional

import strawberry
from strawberry.types import Info

from recommendations.models import Material
from recommendations.types import MaterialType


@strawberry.type
class MaterialsQuery:
    @strawberry.field()
    def material(self, info: Info, id: int) -> Optional[MaterialType]:
        try:
            return Material.objects.get(pk=id)
        except Material.DoesNotExist:
            return None

    @strawberry.field()
    def materials(self, info: Info, action_id: int) -> List[MaterialType]:
        return Material.objects.filter(action_id=action_id)
