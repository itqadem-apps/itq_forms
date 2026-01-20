import strawberry
from app.auth import strawberry_auth
from strawberry.types import Info

RequireAuth = strawberry_auth.require_authenticated()


@strawberry.type
class MeQuery:
    @strawberry.field(permission_classes=[RequireAuth])
    def me(self, info: Info) -> str:
        return info.context.user.identity.preferred_username
