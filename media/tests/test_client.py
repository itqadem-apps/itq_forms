from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest

from media import client as media_client

TOKEN_URL = "https://kc.example/realms/Itqadem/protocol/openid-connect/token"


@pytest.fixture
def media(settings):
    settings.MEDIA_TRANSPORT = "grpc"
    settings.MEDIA_GRPC_TARGET = "media-grpc.example:50051"
    settings.MEDIA_LIBRARY_URL = "https://media.example/"
    settings.KEYCLOAK_BASE_URL = "https://kc.example"
    settings.KEYCLOAK_REALM = "Itqadem"
    settings.KEYCLOAK_CLIENT_ID = "forms-api"
    settings.KEYCLOAK_CLIENT_SECRET = "s3cret"
    media_client.reset_clients()
    yield settings
    media_client.reset_clients()


def test_one_grpc_client_per_process(media) -> None:
    first = media_client.build_client()
    assert first is not None
    assert first.transport == "grpc"
    assert media_client.build_client() is first


def test_access_goes_over_http_as_forms_api_without_tenant(media, monkeypatch: pytest.MonkeyPatch) -> None:
    issued: list[dict[str, list[str]]] = []
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOKEN_URL:
            issued.append(parse_qs(request.content.decode()))
            return httpx.Response(200, json={"access_token": "kc-1", "expires_in": 300})
        seen.append(request)
        return httpx.Response(200, json={"items": [], "granted": 1, "failed": 0})

    for name in ("Client", "AsyncClient"):
        real = getattr(httpx, name)

        def mocked(*args, _real=real, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handle)
            return _real(*args, **kwargs)

        monkeypatch.setattr(httpx, name, mocked)

    http = media_client.build_http_client()
    assert http is not None
    assert http.transport == "http"
    assert http is not media_client.build_client()
    assert media_client.build_http_client() is http

    with pytest.warns(DeprecationWarning):
        result = http.access.bulk_grant(asset_ids=["a"], user_id="u")
    assert result.granted == 1
    assert issued[0]["client_id"] == ["forms-api"]
    assert issued[0]["client_secret"] == ["s3cret"]
    assert issued[0]["grant_type"] == ["client_credentials"]
    (request,) = seen
    assert request.headers["Authorization"] == "Bearer kc-1"
    assert "X-Tenant" not in request.headers
    assert str(request.url).startswith("https://media.example/")


def test_http_transport_shares_one_client(media) -> None:
    media.MEDIA_TRANSPORT = "http"
    client = media_client.build_client()
    assert client is not None and client.transport == "http"
    assert media_client.build_http_client() is client


def test_resolving_is_grpc_whatever_the_transport(media) -> None:
    """Media removes HTTP /delivery: the gate's client is always gRPC."""
    assert media_client.build_grpc_client() is media_client.build_client()

    media_client.reset_clients()
    media.MEDIA_TRANSPORT = "http"
    grpc = media_client.build_grpc_client()
    assert grpc is not None and grpc.transport == "grpc"
    assert grpc is not media_client.build_client()
    assert media_client.build_grpc_client() is grpc


def test_the_gate_is_built_on_the_grpc_client(media, monkeypatch: pytest.MonkeyPatch) -> None:
    from media import views

    media.MEDIA_TRANSPORT = "http"
    monkeypatch.setattr(views, "_gate", None)
    assert views._get_gate()._client.transport == "grpc"


def test_the_default_target_is_the_cluster_name() -> None:
    from django.conf import settings

    assert settings.MEDIA_GRPC_TARGET == "media-grpc-svc.itqadem.svc.cluster.local:50051"


def test_unknown_transport_fails_loudly(media) -> None:
    media.MEDIA_TRANSPORT = "carrier-pigeon"
    with pytest.raises(ValueError):
        media_client.build_client()


@pytest.mark.parametrize("unset", ["KEYCLOAK_CLIENT_SECRET", "KEYCLOAK_BASE_URL", "MEDIA_GRPC_TARGET"])
def test_unconfigured_media_builds_nothing(media, unset) -> None:
    setattr(media, unset, "")
    assert media_client.build_client() is None


def test_http_needs_the_url(media) -> None:
    media.MEDIA_LIBRARY_URL = ""
    assert media_client.build_http_client() is None
