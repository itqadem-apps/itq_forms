"""Mode B wiring for itq_forms.

pkg_auth v2.0 middleware (``IdentityMiddleware`` + ``AuthContextMiddleware``,
installed in ``app.settings.MIDDLEWARE``) populates ``request.identity`` and
``request.auth_context`` before the GraphQL view runs. The view's
``get_context`` just surfaces those onto ``info.context`` alongside the
service-specific ``currency`` header.
"""
from __future__ import annotations

from typing import Any

from strawberry.django.views import GraphQLView
from strawberry.permission import BasePermission
from strawberry.types import Info


class _ContextProxy:
    """Shape exposed to every resolver as ``info.context``.

    Attributes:
        request: the Django ``HttpRequest``.
        identity: ``pkg_auth.authentication.IdentityContext`` or ``None``.
        auth_context: ``pkg_auth.authorization.AuthContext`` or ``None``.
        currency: value of the ``X-Currency`` header, if any.
    """

    __slots__ = ("request", "identity", "auth_context", "currency")

    def __init__(self, request, *, currency: str | None = None) -> None:
        self.request = request
        self.identity = getattr(request, "identity", None)
        self.auth_context = getattr(request, "auth_context", None)
        self.currency = currency

    @property
    def user(self):
        # Backward-compat shim: legacy resolvers read ``info.context.user``
        # and then ``user.identity`` / ``user.keycloak_sub``. The new shape
        # carries identity directly, so we expose the identity in both
        # positions via this proxy.
        return _UserShim(self.identity) if self.identity is not None else None


class _UserShim:
    """Presents the new ``IdentityContext`` under the legacy ``user`` name."""

    __slots__ = ("identity",)

    def __init__(self, identity) -> None:
        self.identity = identity

    @property
    def keycloak_sub(self) -> str:
        return self.identity.subject_str


class AuthedGraphQLView(GraphQLView):
    async def get_context(self, request, response):
        currency = request.META.get("HTTP_X_CURRENCY")
        return _ContextProxy(request, currency=currency)


class RequireAuth(BasePermission):
    """Strawberry permission class: require a valid identity."""

    message = "Authentication required"

    def has_permission(self, source: Any, info: Info, **kwargs: Any) -> bool:
        return getattr(info.context, "identity", None) is not None
