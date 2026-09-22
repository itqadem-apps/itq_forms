"""Platform-admin detection for itq_forms.

The package's :func:`pkg_auth.authorization.is_platform_context` is
stateless — it just compares ``auth_ctx.organization_id`` against a
cached platform org id. This module owns the cache. The org_repo +
slug are registered at app-ready time, but the actual DB lookup is
deferred to first use of :func:`is_platform_context` so we don't query
during AppConfig.ready().
"""
from __future__ import annotations

from pkg_auth.authorization import OrgId
from pkg_auth.authorization import is_platform_context as _pkg_is_platform

_platform_org_id: OrgId | None = None
_org_repo = None
_org_slug: str = "platform"
_resolved: bool = False


def register_platform_org_provider(org_repo, slug: str = "platform") -> None:
    """Register the org repo + slug. Does not query the DB."""
    global _org_repo, _org_slug, _resolved
    _org_repo = org_repo
    _org_slug = slug
    _resolved = False


def _ensure_resolved() -> None:
    global _platform_org_id, _resolved
    if _resolved or _org_repo is None:
        return
    from asgiref.sync import async_to_sync

    try:
        org = async_to_sync(_org_repo.get_by_slug)(_org_slug)
    except Exception:
        return
    if org is not None:
        _platform_org_id = org.id
    _resolved = True


def is_platform_context(auth_ctx) -> bool:
    """True when the active ``AuthContext`` is bound to the platform org."""
    _ensure_resolved()
    return _pkg_is_platform(auth_ctx, _platform_org_id)


def ensure_in_org(entity, auth_ctx, *, allow_platform_bypass: bool = True) -> None:
    """Refuse a row that belongs to another organization.

    Ported from ``itq_courses``' ``interface/http/platform.py:57`` — the frozen
    reference model — for SPEC-forms-permission-gates CAP-2. Kept tiny on
    purpose: call it after loading a single row and before returning or
    mutating it. Platform-org callers bypass it deliberately; this is the gate
    where platform scope belongs.

    Pass ``allow_platform_bypass=False`` for owner-axis (tenant-only) actions
    that the platform must NOT perform on a tenant's behalf.

    Raises ``PermissionError``, the same denial the ``check_permission``
    decorator raises, so both gates surface to the client identically.
    """
    if allow_platform_bypass and is_platform_context(auth_ctx):
        return
    entity_org = getattr(entity, "organization_id", None)
    if entity_org is None or entity_org != auth_ctx.organization_id.value:
        raise PermissionError("Resource belongs to another organization")
