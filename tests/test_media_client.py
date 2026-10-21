from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest

from surveys import media_client

TOKEN_URL = "https://kc.example/realms/Itqadem/protocol/openid-connect/token"


@pytest.fixture
def media(settings):
    settings.MEDIA_LIBRARY_URL = "https://media.example/"
    settings.MEDIA_LIBRARY_TENANT_ID = "itqadem"
    settings.KEYCLOAK_BASE_URL = "https://kc.example"
    settings.KEYCLOAK_REALM = "Itqadem"
    settings.KEYCLOAK_CLIENT_ID = "forms-api"
    settings.KEYCLOAK_CLIENT_SECRET = "s3cret"
    media_client._service_http = None
    yield settings
    if media_client._service_http is not None:
        media_client._service_http.close()
    media_client._service_http = None


def test_static_token_wins_while_set(media) -> None:
    media.MEDIA_LIBRARY_TOKEN = "ml_live_x"
    client = media_client.build_client()
    assert client is not None
    assert client._http.headers["Authorization"] == "Bearer ml_live_x"
    client.close()
    assert media_client._service_http is None


def test_without_static_token_calls_media_as_forms(media, monkeypatch: pytest.MonkeyPatch) -> None:
    media.MEDIA_LIBRARY_TOKEN = ""
    issued: list[dict[str, list[str]]] = []
    seen: list[tuple[str, str, str]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URL:
            issued.append(parse_qs(request.content.decode()))
            return httpx.Response(200, json={"access_token": f"kc-{len(issued)}", "expires_in": 300})
        seen.append((request.headers["Authorization"], request.headers["X-Tenant"], str(request.url)))
        return httpx.Response(401 if request.headers["Authorization"] == "Bearer kc-1" else 200)

    real_client = httpx.Client

    def mocked(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handle)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", mocked)

    first = media_client.build_client()
    assert first is not None
    assert first._http.get("/api/v1/assets").status_code == 200
    first.close()
    second = media_client.build_client()
    assert second is not None
    assert second._http.get("/api/v1/assets").status_code == 200
    second.close()

    # One shared pool and token cache across per-call clients; close() keeps it.
    assert second._http is first._http
    assert len(issued) == 2  # the first token, then the refetch after its 401
    assert issued[0]["client_id"] == ["forms-api"]
    assert issued[0]["client_secret"] == ["s3cret"]
    url = "https://media.example/api/v1/assets"
    assert seen == [
        ("Bearer kc-1", "itqadem", url),
        ("Bearer kc-2", "itqadem", url),
        ("Bearer kc-2", "itqadem", url),
    ]


def test_unconfigured_media_builds_nothing(media) -> None:
    media.MEDIA_LIBRARY_URL = ""
    assert media_client.build_client() is None
