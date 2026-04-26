import importlib
import sys
import types

import pytest


models = types.ModuleType("accounts.models")
models.User = object
sys.modules.setdefault("accounts.models", models)
messaging = importlib.import_module("accounts.messaging")


class _Saved:
    id = "user-1"


@pytest.fixture
def db():
    return None


@pytest.mark.asyncio
async def test_auth_user_registered_upserts_forms_user(monkeypatch):
    calls = []

    async def upsert_user(user):
        calls.append(user)
        return _Saved(), True

    monkeypatch.setattr(messaging, "_upsert_user", upsert_user)

    await messaging.handle_auth_user_registered(
        {"event_id": "evt-1", "user": {"id": "user-1", "email": "u@example.com"}},
        "auth.UserRegistered",
    )

    assert calls == [{"id": "user-1", "email": "u@example.com"}]
