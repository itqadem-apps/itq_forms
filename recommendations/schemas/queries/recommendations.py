from typing import List, Optional

import strawberry
from strawberry.types import Info

from recommendations.models import Recommendation
from recommendations.types import RecommendationType


@strawberry.type
class RecommendationsQuery:
    @strawberry.field()
    def recommendation(self, info: Info, id: int) -> Optional[RecommendationType]:
        try:
            return Recommendation.objects.get(pk=id)
        except Recommendation.DoesNotExist:
            return None

    @strawberry.field()
    def recommendations(self, info: Info, survey_id: int) -> List[RecommendationType]:
        return Recommendation.objects.filter(survey_id=survey_id, deleted_at__isnull=True)
