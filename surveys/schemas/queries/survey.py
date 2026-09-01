import strawberry
from strawberry.types import Info

from surveys.models import Survey
from surveys.types import SurveyType
from app.graphql_ids import as_pk


@strawberry.type
class SurveyQuery:
    @strawberry.field()
    def survey(self, info: Info, id: strawberry.ID) -> SurveyType | None:
        id = as_pk(id)
        try:
            return Survey.objects.get(pk=id, deleted_at__isnull=True)
        except Survey.DoesNotExist:
            return None
