from typing import List, Optional

import strawberry
from strawberry.types import Info

from classifications.models import Classification
from classifications.types import ClassificationType


@strawberry.type
class ClassificationsQuery:
    @strawberry.field()
    def classification(self, info: Info, id: int) -> Optional[ClassificationType]:
        try:
            return Classification.objects.get(pk=id)
        except Classification.DoesNotExist:
            return None

    @strawberry.field()
    def classifications(self, info: Info, survey_id: int) -> List[ClassificationType]:
        return Classification.objects.filter(survey_id=survey_id, deleted_at__isnull=True)
