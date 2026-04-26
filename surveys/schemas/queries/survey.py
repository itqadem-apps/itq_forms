import strawberry
from strawberry.types import Info

from surveys.models import Survey
from surveys.types import SurveyType


@strawberry.type
class SurveyQuery:
    @strawberry.field()
    def survey(self, info: Info, id: int) -> SurveyType | None:
        try:
            return Survey.objects.get(pk=id)
        except Survey.DoesNotExist:
            return None
