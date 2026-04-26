"""Platform-admin detection for itq_forms.

The package's :func:`pkg_auth.authorization.is_platform_context` is
stateless — it just compares ``auth_ctx.organization_id`` against a
cached platform org id. This module owns the cache (populated once at
startup from :setting:`PLATFORM_ORG_SLUG`) and exposes a service-level
wrapper with no arguments.
"""
from __future__ import annotations

from pkg_auth.authorization import OrgId
from pkg_auth.authorization import is_platform_context as _pkg_is_platform

_platform_org_id: OrgId | None = None


def init_platform_org_id_sync(org_repo) -> None:
    """Resolve the platform org by slug and cache its id. Idempotent."""
    from asgiref.sync import async_to_sync
    from django.conf import settings

    global _platform_org_id
    slug = getattr(settings, "PLATFORM_ORG_SLUG", "platform")
    org = async_to_sync(org_repo.get_by_slug)(slug)
    if org is not None:
        _platform_org_id = org.id


def is_platform_context(auth_ctx) -> bool:
    """True when the active ``AuthContext`` is bound to the platform org."""
    return _pkg_is_platform(auth_ctx, _platform_org_id)
