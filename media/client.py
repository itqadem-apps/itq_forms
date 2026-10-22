from __future__ import annotations

import threading
from typing import Literal, cast

from django.conf import settings
from pkg_media import MediaClient

Transport = Literal["http", "grpc"]

_lock = threading.Lock()
# The process-wide client over MEDIA_TRANSPORT, and a second one over HTTP for
# the deprecated HTTP-only client.access / client.policies (and file bytes,
# which never travel over gRPC).
_client: MediaClient | None = None
_http_client: MediaClient | None = None


def _configured(transport: str) -> bool:
    if transport == "http" and not settings.MEDIA_LIBRARY_URL:
        return False
    if transport == "grpc" and not settings.MEDIA_GRPC_TARGET:
        return False
    return bool(
        settings.KEYCLOAK_BASE_URL
        and settings.KEYCLOAK_REALM
        and settings.KEYCLOAK_CLIENT_ID
        and settings.KEYCLOAK_CLIENT_SECRET
    )


def _new_client(transport: Transport) -> MediaClient:
    base = (settings.KEYCLOAK_BASE_URL or "").rstrip("/")
    return MediaClient(
        transport=transport,
        base_url=settings.MEDIA_LIBRARY_URL or None,
        target=settings.MEDIA_GRPC_TARGET or None,
        token_url=f"{base}/realms/{settings.KEYCLOAK_REALM}/protocol/openid-connect/token",
        client_id=settings.KEYCLOAK_CLIENT_ID,
        client_secret=settings.KEYCLOAK_CLIENT_SECRET,
    )


def build_client() -> MediaClient | None:
    """The process-wide media client, calling media as forms' own Keycloak
    client (forms-api, KEYCLOAK_CLIENT_SECRET, audience media-api) over
    MEDIA_TRANSPORT. It is thread-safe and caches and refreshes its own token,
    so callers share it and never close it. None when media or the credentials
    are unset, and forms runs without media."""
    global _client
    if not _configured(settings.MEDIA_TRANSPORT):
        return None
    with _lock:
        if _client is None:
            # An unknown MEDIA_TRANSPORT fails here, loudly, in MediaClient.
            _client = _new_client(cast(Transport, settings.MEDIA_TRANSPORT))
        return _client


def build_http_client() -> MediaClient | None:
    """The process-wide client over HTTP, whatever MEDIA_TRANSPORT says, for
    the deprecated HTTP-only client.access and client.policies. Shared like
    build_client(): never close it."""
    global _http_client
    if not _configured("http"):
        return None
    client = build_client()
    if client is not None and client.transport == "http":
        return client
    with _lock:
        if _http_client is None:
            _http_client = _new_client("http")
        return _http_client


def reset_clients() -> None:
    """Forget the shared clients (tests, settings changes)."""
    global _client, _http_client
    with _lock:
        for client in (_client, _http_client):
            if client is not None:
                client.close()
        _client = _http_client = None
