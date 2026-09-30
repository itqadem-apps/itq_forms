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
from app.messaging.handlers.taxonomy_events import TaxonomyCategoryEventSubscriber
from app.messaging.handlers.users_child_events import UsersChildEventSubscriber
from app.messaging.handlers import recommendable_events
from app.messaging import registry as registry_module
from app.messaging.registry import register_handlers
from unimessaging.broker.registry import HandlerRegistry, _default_registry


RECOMMENDABLE_EVENTS = [
    "courses.course.created",
    "courses.course.updated",
    "courses.course.deleted",
    "videos.playlist.created",
    "articles.activity.created",
    "reservations.meeting.session_cancelled",
]


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
    # Real event names are 3 tokens; a 2-token probe passed while `courses.*` dropped
    # every one of them (estate task #157).
    for subject in RECOMMENDABLE_EVENTS:
        assert isinstance(
            fresh_registry.resolve_handler(subject).__self__,
            RecommendableEventSubscriber,
        ), subject
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
    assert isinstance(
        fresh_registry.resolve_handler("taxonomy.category.updated").__self__,
        TaxonomyCategoryEventSubscriber,
    )


@pytest.mark.asyncio
async def test_a_course_lifecycle_event_reaches_the_exam_handler(fresh_registry, monkeypatch):
    seen: list[tuple[str, str]] = []

    def record(name):
        async def handler(payload, subject):
            seen.append((name, subject))
        return handler

    monkeypatch.setattr(recommendable_events, "handle_recommendable_event", record("catalog"))
    monkeypatch.setattr(recommendable_events, "handle_courses_event", record("exam"))
    register_handlers()

    handler = fresh_registry.resolve_handler("courses.course.created")
    await handler({"aggregate_id": "c1"}, "courses.course.created")

    assert seen == [("catalog", "courses.course.created"), ("exam", "courses.course.created")]


def test_default_registry_is_used_by_runtime():
    """Sanity check: the runtime relies on the unimessaging default registry."""
    from app.messaging import runtime  # noqa: F401

    assert _default_registry is not None
