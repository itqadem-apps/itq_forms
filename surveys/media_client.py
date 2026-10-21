from __future__ import annotations

import threading

import httpx
from django.conf import settings
from pkg_auth.authentication.adapters.keycloak import (
    ServiceCredentials,
    ServiceTokenAuth,
    ServiceTokenProvider,
)
from saas_media_library import MediaLibraryClient

_lock = threading.Lock()
_service_http: httpx.Client | None = None


def _shared_service_http() -> httpx.Client:
    """One httpx client per process that authenticates as forms' own Keycloak
    client. Callers build and close a MediaLibraryClient per call; sharing this
    keeps one token cache and one connection pool (close() leaves it open)."""
    global _service_http
    with _lock:
        if _service_http is None:
            provider = ServiceTokenProvider(
                ServiceCredentials.for_realm(
                    base_url=settings.KEYCLOAK_BASE_URL or "",
                    realm=settings.KEYCLOAK_REALM or "",
                    client_id=settings.KEYCLOAK_CLIENT_ID,
                    client_secret=settings.KEYCLOAK_CLIENT_SECRET or "",
                )
            )
            _service_http = httpx.Client(
                base_url=settings.MEDIA_LIBRARY_URL.rstrip("/"),
                headers={"X-Tenant": settings.MEDIA_LIBRARY_TENANT_ID},
                timeout=30.0,
                auth=ServiceTokenAuth(provider),
            )
        return _service_http


def build_client() -> MediaLibraryClient | None:
    if not settings.MEDIA_LIBRARY_URL or not settings.MEDIA_LIBRARY_TENANT_ID:
        return None
    # The static ml_live_ token wins while it is set; without it, forms calls
    # media as itself (KEYCLOAK_CLIENT_ID / KEYCLOAK_CLIENT_SECRET).
    if settings.MEDIA_LIBRARY_TOKEN:
        return MediaLibraryClient(
            base_url=settings.MEDIA_LIBRARY_URL,
            tenant_id=settings.MEDIA_LIBRARY_TENANT_ID,
            token=settings.MEDIA_LIBRARY_TOKEN,
        )
    return MediaLibraryClient(
        base_url=settings.MEDIA_LIBRARY_URL,
        tenant_id=settings.MEDIA_LIBRARY_TENANT_ID,
        http_client=_shared_service_http(),
    )
