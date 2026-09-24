import strawberry
from strawberry.types import Info

from surveys.models import Survey
from surveys.types import SurveyType
from app.graphql_ids import as_pk
from app.platform import PUBLIC_STATUS, ensure_in_org


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
        # organization may not read another organization's row.
        auth_ctx = getattr(info.context, "auth_context", None)
        if auth_ctx is None:
            # The open question that used to sit here is answered: this detail
            # endpoint IS a public catalog read, and the public set is the
            # published one (ruled 2026-09-24, same ruling as
            # `scope_listing_to_caller`). `None` also covers an authenticated
            # caller whose context failed to resolve, who used to reach any row
            # by id — the read half of the exposure this closes.
            #
            # Unpublished returns None rather than raising, matching the
            # DoesNotExist arm above: a caller who may not see the row cannot
            # tell it from one that does not exist.
            return survey if survey.status == PUBLIC_STATUS else None
        ensure_in_org(survey, auth_ctx)
        return survey
