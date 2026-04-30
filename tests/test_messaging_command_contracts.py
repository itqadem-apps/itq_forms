from __future__ import annotations

import asyncio
import os

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
django.setup()

from app import messaging_contract as contract
from app.messaging.handlers.auth_events import AuthEventSubscriber
from app.messaging.handlers.curriculum_events import CurriculumEventSubscriber
from app.messaging.handlers.order_events import OrderEventSubscriber
from app.messaging.handlers.recommendable_events import RecommendableEventSubscriber
from app.messaging.handlers.users_child_events import UsersChildEventSubscriber
from app.messaging import registry as registry_module
from app.messaging.registry import register_handlers
from surveys.management.commands import outbox_relay as outbox_module
from unimessaging.broker.registry import HandlerRegistry, _default_registry


@pytest.fixture
def db():
    return None


@pytest.fixture
def fresh_registry(monkeypatch):
    """Replace the unimessaging default registry for the duration of a test."""
    new_registry = HandlerRegistry()
    monkeypatch.setattr(registry_module, "register_handler", new_registry.register_handler)
    return new_registry


def test_register_handlers_wires_every_contract_subject(fresh_registry):
    register_handlers()

    assert isinstance(
        fresh_registry.resolve_handler("auth.UserRegistered").__self__,
        AuthEventSubscriber,
    )
    assert isinstance(
        fresh_registry.resolve_handler("courses.curriculum_reference").__self__,
        CurriculumEventSubscriber,
    )
    assert isinstance(
        fresh_registry.resolve_handler("courses.curriculum_enrollment").__self__,
        CurriculumEventSubscriber,
    )
    for subject in contract.RECOMMENDABLE_SUBJECTS:
        probe = subject.replace(".>", ".probe").replace(">", "probe")
        assert isinstance(
            fresh_registry.resolve_handler(probe).__self__,
            RecommendableEventSubscriber,
        )
    assert isinstance(
        fresh_registry.resolve_handler("users.child.created").__self__,
        UsersChildEventSubscriber,
    )
    assert isinstance(
        fresh_registry.resolve_handler("users.child_guardian.added").__self__,
        UsersChildEventSubscriber,
    )
    for subject in contract.ORDERS_EVENT_SUBJECTS:
        assert isinstance(
            fresh_registry.resolve_handler(subject).__self__,
            OrderEventSubscriber,
        )


def test_outbox_relay_starts_publish_only_forms_broker(monkeypatch):
    captured = {}

    async def _fake_start_messaging(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(outbox_module, "start_messaging", _fake_start_messaging)

    loop = asyncio.new_event_loop()
    try:
        outbox_module.start_outbox_messaging(loop)
    finally:
        loop.close()

    assert captured["stream_name"] == contract.FORMS_STREAM_NAME
    assert captured["stream_subjects"] == contract.FORMS_STREAM_SUBJECTS
    # Outbox relay no longer wires consumers; ASGI lifespan owns consumption.
    assert "consumers" not in captured
    assert "registry" not in captured


def test_default_registry_is_used_by_runtime():
    """Sanity check: the runtime relies on the unimessaging default registry."""
    from app.messaging import runtime  # noqa: F401

    assert _default_registry is not None
