from typing import List, Optional

import strawberry
from strawberry.types import Info

from recommendations.models import Action
from recommendations.types import ActionType
from app.graphql_ids import as_pk


@strawberry.type
class ActionsQuery:
    @strawberry.field()
    def action(self, info: Info, id: strawberry.ID) -> Optional[ActionType]:
        id = as_pk(id)
        try:
            return Action.objects.get(pk=id)
        except Action.DoesNotExist:
            return None

    @strawberry.field()
    def actions(self, info: Info, survey_id: strawberry.ID) -> List[ActionType]:
        survey_id = as_pk(survey_id)
        return Action.objects.filter(survey_id=survey_id)
