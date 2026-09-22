import strawberry
from strawberry.types import Info

from surveys.models import Survey
from surveys.types import SurveyType
from app.graphql_ids import as_pk
from app.platform import ensure_in_org


@strawberry.type
class SurveyQuery:
    @strawberry.field()
    def survey(self, info: Info, id: strawberry.ID) -> SurveyType | None:
        id = as_pk(id)
        try:
            survey = Survey.objects.get(pk=id, deleted_at__isnull=True)
        except Survey.DoesNotExist:
            return None
        # SPEC-forms-permission-gates CAP-2: a caller acting inside an
        # organization may not read another organization's row. Callers with no
        # auth context are left alone — whether this detail endpoint is a public
        # catalog read is the open question that also blocks CAP-3's list
        # scoping, and this story does not settle it.
        auth_ctx = getattr(info.context, "auth_context", None)
        if auth_ctx is not None:
            ensure_in_org(survey, auth_ctx)
        return survey
