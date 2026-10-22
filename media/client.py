from __future__ import annotations

import threading

from django.conf import settings
from pkg_media import MediaClient

_lock = threading.Lock()
# The process-wide client, over gRPC: forms sends no upload bytes (browsers
# upload to media), so it needs no HTTP address.
_client: MediaClient | None = None


def _configured() -> bool:
    return bool(
        settings.MEDIA_GRPC_TARGET
        and settings.KEYCLOAK_BASE_URL
        and settings.KEYCLOAK_REALM
        and settings.KEYCLOAK_CLIENT_ID
        and settings.KEYCLOAK_CLIENT_SECRET
    )


def _new_client() -> MediaClient:
    base = (settings.KEYCLOAK_BASE_URL or "").rstrip("/")
    return MediaClient(
        transport="grpc",
        target=settings.MEDIA_GRPC_TARGET,
        token_url=f"{base}/realms/{settings.KEYCLOAK_REALM}/protocol/openid-connect/token",
        client_id=settings.KEYCLOAK_CLIENT_ID,
        client_secret=settings.KEYCLOAK_CLIENT_SECRET,
    )


def build_client() -> MediaClient | None:
    """The process-wide media client, calling media as forms' own Keycloak
    client (forms-api, KEYCLOAK_CLIENT_SECRET, audience media-api) over gRPC at
    MEDIA_GRPC_TARGET. It is thread-safe and caches and refreshes its own token,
    so callers share it and never close it. None when the target or the
    credentials are unset, and forms runs without media."""
    global _client
    if not _configured():
        return None
    with _lock:
        if _client is None:
            _client = _new_client()
        return _client


def reset_clients() -> None:
    """Forget the shared client (tests, settings changes)."""
    global _client
    with _lock:
        if _client is not None:
            _client.close()
        _client = None
