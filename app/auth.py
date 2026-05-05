"""Mode B wiring for itq_forms.

pkg_auth v2.0 middleware (``IdentityMiddleware`` + ``AuthContextMiddleware``,
installed in ``app.settings.MIDDLEWARE``) populates ``request.identity`` and
``request.auth_context`` before the GraphQL view runs. The view's
``get_context`` just surfaces those onto ``info.context`` alongside the
service-specific ``currency`` header.
"""
from __future__ import annotations

import logging
from typing import Any

from strawberry.django.views import GraphQLView
from strawberry.permission import BasePermission
from strawberry.types import Info

from asgiref.sync import iscoroutinefunction
from uuid import UUID

from pkg_auth.authentication import (
    AuthenticationError,
    InvalidTokenError,
    TokenExpiredError,
)
from pkg_auth.authorization import (
    NotAMember,
    OrgId,
    UnknownOrganization,
    UserNotProvisioned,
)
from pkg_auth.integrations.django import IdentityMiddleware as _BaseIdentityMiddleware
from pkg_auth.integrations.django.install import get_registry
from pkg_auth.integrations.django.middleware import _extract_token

logger = logging.getLogger(__name__)


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


class AuthedGraphQLView(GraphQLView):
    def get_context(self, request, response):
        currency = request.META.get("HTTP_X_CURRENCY")
        return _ContextProxy(request, currency=currency)


class LoggingIdentityMiddleware(_BaseIdentityMiddleware):
    """IdentityMiddleware that logs token-rejection reasons.

    pkg_auth's base middleware silently sets ``request.identity = None``
    on every auth failure (audience/issuer mismatch, expired, bad
    signature). That makes config drift indistinguishable from "no token
    sent" — every request quietly degrades to anonymous. This subclass
    logs a WARNING with the exception class and message so misconfigured
    audiences/issuers are visible.
    """

    def __call__(self, request):
        registry = get_registry()
        token = _extract_token(request, registry.cookie_name)
        request.identity = None
        if token is not None:
            try:
                request.identity = registry.authenticate.execute(token)
            except (TokenExpiredError, InvalidTokenError, AuthenticationError) as exc:
                logger.warning(
                    "pkg_auth: token rejected (%s): %s",
                    type(exc).__name__,
                    exc,
                )
        return self.get_response(request)


class OptionalAuthContextMiddleware:
    """Soft replacement for ``pkg_auth.AuthContextMiddleware``.

    The packaged middleware 401s/403s/404s whenever ``X-Organization-Id``
    is sent but identity / org / membership doesn't fully resolve. That
    breaks public listing/detail queries any time the frontend attaches
    the org header for a logged-out user.

    Here every failure is *soft*: ``request.auth_context`` is set to
    ``None`` and the request continues. Schema-level permissions
    (``RequireAuth`` / ``RequireAuthContext``) gate the writes that
    actually need identity or org membership.
    """

    sync_capable = False
    async_capable = True

    def __init__(self, get_response):
        self.get_response = get_response
        if not iscoroutinefunction(get_response):
            raise RuntimeError(
                "OptionalAuthContextMiddleware requires the async middleware "
                "chain (ASGI / runserver)."
            )

    async def __call__(self, request):
        registry = get_registry()
        request.auth_context = None

        raw = request.headers.get(registry.header_name)
        if raw is None:
            return await self.get_response(request)

        identity = getattr(request, "identity", None)
        if identity is None:
            return await self.get_response(request)

        try:
            if registry.sync_user is not None:
                user = await registry.sync_user.execute(
                    sub=identity.subject_str,
                    email=identity.email_str or "",
                    full_name=identity.full_name,
                )
            else:
                assert registry.resolve_user is not None
                user = await registry.resolve_user.execute(sub=identity.subject_str)
        except UserNotProvisioned:
            return await self.get_response(request)

        try:
            org = await registry.organization_repo.get(OrgId(UUID(raw)))
        except (ValueError, AttributeError):
            org = await registry.organization_repo.get_by_slug(raw)
        if org is None:
            return await self.get_response(request)

        try:
            request.auth_context = await registry.resolve_auth.execute(user.id, org.id)
        except (NotAMember, UnknownOrganization):
            request.auth_context = None

        return await self.get_response(request)


class RequireAuth(BasePermission):
    """Strawberry permission class: require a valid identity."""

    message = "Authentication required"

    def has_permission(self, source: Any, info: Info, **kwargs: Any) -> bool:
        return getattr(info.context, "identity", None) is not None


class RequireAuthContext(BasePermission):
    """Require both a valid identity AND a resolved org membership."""

    message = "Organization context required"

    def has_permission(self, source: Any, info: Info, **kwargs: Any) -> bool:
        ctx = info.context
        return (
            getattr(ctx, "identity", None) is not None
            and getattr(ctx, "auth_context", None) is not None
        )
