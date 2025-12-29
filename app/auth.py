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

class AuthedGraphQLView(GraphQLView):
    def get_context(self, request, response):
        return context_getter(request, response)