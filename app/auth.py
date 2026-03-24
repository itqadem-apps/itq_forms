from django.conf import settings
from pkg_auth.integrations.django import create_django_auth
from pkg_auth.integrations.strawberry import create_strawberry_auth
from strawberry.django.views import GraphQLView

authz = create_django_auth(
    keycloak_base_url=settings.KEYCLOAK_BASE_URL,
    realm=settings.KEYCLOAK_REALM,
    client_id=settings.KEYCLOAK_CLIENT_ID,
    audience=getattr(settings, "KEYCLOAK_AUDIENCE", None),
)

strawberry_auth = create_strawberry_auth(
    keycloak_base_url=settings.KEYCLOAK_BASE_URL,
    realm=settings.KEYCLOAK_REALM,
    client_id=settings.KEYCLOAK_CLIENT_ID,
    audience=getattr(settings, "KEYCLOAK_AUDIENCE", None),
)

context_getter = strawberry_auth.make_django_context_getter(optional=True)


class _ContextProxy:
    """Wraps the auth context and adds extra request-derived attributes."""

    def __init__(self, auth_ctx, **extras):
        self._auth_ctx = auth_ctx
        self._extras = extras

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self._extras:
            return self._extras[name]
        return getattr(self._auth_ctx, name)


class AuthedGraphQLView(GraphQLView):
    def get_context(self, request, response):
        ctx = context_getter(request, response)
        currency = request.META.get("HTTP_X_CURRENCY")
        return _ContextProxy(ctx, currency=currency)
