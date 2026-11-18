from typing import List, Optional

import strawberry
from strawberry.types import Info

from app.graphql_ids import as_pk
from app.platform import is_platform_context
from recommendations import catalog
from recommendations.models import Recommendable
from recommendations.types import RecommendableType


RECOMMENDABLES_LIMIT = 20


@strawberry.type
class RecommendablesQuery:
    @strawberry.field()
    def recommendable(self, info: Info, id: strawberry.ID) -> Optional[RecommendableType]:
        id = as_pk(id)
        try:
            return Recommendable.objects.get(pk=id)
        except Recommendable.DoesNotExist:
            return None

    @strawberry.field()
    def recommendables(
        self, info: Info, search: Optional[str] = None, language: Optional[str] = None
    ) -> List[RecommendableType]:
        """The courses an admin can pin to an action band (intake report #134 ruling).

        A caller sees only their own organization's courses; a platform caller sees every
        organization's; a course with no organization is hidden from everyone, and a caller
        with no auth context gets an empty list. Only courses whose last event is not a
        deletion are offered. Results match ``search`` on any title, are ordered by the title
        shown in ``language``, and stop at RECOMMENDABLES_LIMIT (20), with no paging.
        """
        auth_ctx = getattr(info.context, "auth_context", None)
        if auth_ctx is None:
            return []
        platform = is_platform_context(auth_ctx)
        caller_org = str(auth_ctx.organization_id.value) if auth_ctx.organization_id else None

        rows = Recommendable.objects.filter(
            source_service=catalog.COURSE_SERVICE,
            source_model=catalog.COURSE_MODEL,
        )

        shown = []
        for row in rows:
            # Filtered here, not with exclude(): on Postgres, NOT over a JSON key drops rows missing the key.
            if isinstance(row.data, dict) and row.data.get("subject") == catalog.COURSE_DELETED:
                continue
            org = catalog.organization_id(row.data)
            if org is None or not (platform or org == caller_org):
                continue
            if not catalog.matches(row.data, search):
                continue
            title = catalog.shown_title(row.data, language)
            shown.append(((title is None, (title or "").casefold(), row.pk), row))
        shown.sort(key=lambda pair: pair[0])
        return [row for _, row in shown[:RECOMMENDABLES_LIMIT]]
