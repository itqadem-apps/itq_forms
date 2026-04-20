import strawberry
from app.auth import RequireAuth
from strawberry.types import Info


@strawberry.type
class MeQuery:
    @strawberry.field(permission_classes=[RequireAuth])
    def me(self, info: Info) -> str:
        return info.context.identity.preferred_username
