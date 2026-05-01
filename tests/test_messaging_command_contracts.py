from __future__ import annotations

import os

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
django.setup()

from app import messaging_contract as contract
from app.messaging.handlers.auth_events import AuthEventSubscriber
from app.messaging.handlers.external_reference_events import ExternalReferenceEventSubscriber
from app.messaging.handlers.order_events import OrderEventSubscriber
from app.messaging.handlers.recommendable_events import RecommendableEventSubscriber
from app.messaging.handlers.users_child_events import UsersChildEventSubscriber
from app.messaging import registry as registry_module
from app.messaging.registry import register_handlers
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
        fresh_registry.resolve_handler("courses.external_reference").__self__,
        ExternalReferenceEventSubscriber,
    )
    assert isinstance(
        fresh_registry.resolve_handler("courses.external_enrollment").__self__,
        ExternalReferenceEventSubscriber,
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


def test_default_registry_is_used_by_runtime():
    """Sanity check: the runtime relies on the unimessaging default registry."""
    from app.messaging import runtime  # noqa: F401

    assert _default_registry is not None
