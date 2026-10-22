from __future__ import annotations


import pytest

from media import client as media_client


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


def test_http_transport_shares_one_client(media) -> None:
    media.MEDIA_TRANSPORT = "http"
    client = media_client.build_client()
    assert client is not None and client.transport == "http"


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
    media.MEDIA_TRANSPORT = "http"
    media.MEDIA_LIBRARY_URL = ""
    assert media_client.build_client() is None
