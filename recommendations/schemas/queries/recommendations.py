from typing import List, Optional

import strawberry
from strawberry.types import Info

from recommendations.models import Recommendation
from recommendations.types import RecommendationType
from app.graphql_ids import as_pk


@strawberry.type
class RecommendationsQuery:
    @strawberry.field()
    def recommendation(self, info: Info, id: strawberry.ID) -> Optional[RecommendationType]:
        id = as_pk(id)
        try:
            return Recommendation.objects.get(pk=id)
        except Recommendation.DoesNotExist:
            return None

    @strawberry.field()
    def recommendations(self, info: Info, survey_id: strawberry.ID) -> List[RecommendationType]:
        survey_id = as_pk(survey_id)
        return Recommendation.objects.filter(survey_id=survey_id, deleted_at__isnull=True)
