from __future__ import annotations


import pytest

from media import client as media_client


@pytest.fixture
def media(settings):
    settings.MEDIA_GRPC_TARGET = "media-grpc.example:50051"
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


def test_builds_a_grpc_client_at_the_target(media, monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[dict] = []
    monkeypatch.setattr(media_client, "MediaClient", lambda **kwargs: built.append(kwargs) or object())
    assert media_client.build_client() is not None
    assert built == [
        {
            "transport": "grpc",
            "target": "media-grpc.example:50051",
            "token_url": "https://kc.example/realms/Itqadem/protocol/openid-connect/token",
            "client_id": "forms-api",
            "client_secret": "s3cret",
        }
    ]
    media_client._client = None


def test_the_gate_is_built_on_the_grpc_client(media, monkeypatch: pytest.MonkeyPatch) -> None:
    from media import views

    monkeypatch.setattr(views, "_gate", None)
    assert views._get_gate()._client.transport == "grpc"


def test_the_default_target_is_the_cluster_name() -> None:
    from django.conf import settings

    assert settings.MEDIA_GRPC_TARGET == "media-grpc-svc.itqadem.svc.cluster.local:50051"


def test_settings_read_no_transport_or_http_address() -> None:
    from app import settings as app_settings

    assert not hasattr(app_settings, "MEDIA_TRANSPORT")
    assert not hasattr(app_settings, "MEDIA_LIBRARY_URL")


@pytest.mark.parametrize("unset", ["KEYCLOAK_CLIENT_SECRET", "KEYCLOAK_BASE_URL", "MEDIA_GRPC_TARGET"])
def test_unconfigured_media_builds_nothing(media, unset) -> None:
    setattr(media, unset, "")
    assert media_client.build_client() is None
