from typing import List, Optional

import strawberry
from strawberry.types import Info

from classifications.models import Classification
from classifications.types import ClassificationType
from app.graphql_ids import as_pk


@strawberry.type
class ClassificationsQuery:
    @strawberry.field()
    def classification(self, info: Info, id: strawberry.ID) -> Optional[ClassificationType]:
        id = as_pk(id)
        try:
            return Classification.objects.get(pk=id)
        except Classification.DoesNotExist:
            return None

    @strawberry.field()
    def classifications(self, info: Info, survey_id: strawberry.ID) -> List[ClassificationType]:
        survey_id = as_pk(survey_id)
        return Classification.objects.filter(survey_id=survey_id, deleted_at__isnull=True)
