from typing import List, Optional

import strawberry
from strawberry.types import Info

from recommendations.models import Action
from recommendations.types import ActionType


@strawberry.type
class ActionsQuery:
    @strawberry.field()
    def action(self, info: Info, id: int) -> Optional[ActionType]:
        try:
            return Action.objects.get(pk=id)
        except Action.DoesNotExist:
            return None

    @strawberry.field()
    def actions(self, info: Info, survey_id: int) -> List[ActionType]:
        return Action.objects.filter(survey_id=survey_id)
