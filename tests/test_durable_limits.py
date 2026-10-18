"""Every durable forms binds is bounded (estate:AD-22).

The enumeration runs `start_consumers()` against fake brokers and collects what is
actually bound, so a durable added anywhere the runtime reaches -- a contract
list, a builder or the runtime itself -- fails here unless it declares limits.
"""
import asyncio
import logging
import os

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
django.setup()

from app.messaging import runtime
from external_references.consumer import (
    handle_external_enrollment_event,
    handle_external_reference_event,
)

# Renaming a durable replays its stream (estate:AD-15), so the names are pinned.
EXPECTED_DURABLES = {
    "forms-auth-user-registered-consumer",
    "forms-external-reference-events-consumer",
    "forms-external-reference-events-consumer-enrollment",
    "forms-recommendables-courses-consumer",
    "forms-recommendables-videos-consumer",
    "forms-recommendables-articles-consumer",
    "forms-recommendables-reservations-consumer",
    "forms-users-child-consumer",
    "forms-users-child_guardian-consumer",
    "forms-orders-order-consumer",
    "forms-taxonomy-category-consumer",
}


class _FakeBroker:
    def __init__(self, *, consumers=None, **_kwargs):
        self.consumers = list(consumers or [])
        _FakeBroker.instances.append(self)

    async def start(self):
        pass

    async def stop(self):
        pass


@pytest.fixture
def bound_consumers(monkeypatch, tmp_path):
    _FakeBroker.instances = []
    monkeypatch.setattr(runtime, "UnifiedMessageBroker", _FakeBroker)
    monkeypatch.setattr(runtime, "_consumer_brokers", [])

    heartbeat = runtime.AllBrokersTicked(
        tmp_path / "heartbeat", runtime.CONSUMER_BROKER_LABELS
    )
    asyncio.run(runtime.start_consumers(heartbeat))
    return [c for b in _FakeBroker.instances for c in b.consumers]


def test_runtime_binds_the_eleven_known_durables(bound_consumers):
    durables = [c.durable for c in bound_consumers]
    assert len(durables) == len(set(durables)), durables
    assert set(durables) == EXPECTED_DURABLES


def test_every_bound_durable_declares_the_estate_defaults(bound_consumers):
    unbounded = [c.durable for c in bound_consumers if c.limits is None]
    assert not unbounded, f"durables bound without estate:AD-22 limits: {unbounded}"
    # The estate:AD-22 values themselves, not whatever the package defaults to.
    for c in bound_consumers:
        assert c.limits.max_deliver == 5, c.durable
        assert c.limits.ack_wait == 60.0, c.durable
        assert c.limits.nak_delays == (1.0, 5.0, 30.0, 120.0), c.durable


SENTINEL = "learner-secret-7f3a"


@pytest.mark.parametrize(
    "handler, field, subject",
    [
        (handle_external_reference_event, "collection_id", "courses.external_reference"),
        (handle_external_enrollment_event, "usage_limit", "courses.external_enrollment"),
    ],
)
def test_invalid_payload_is_logged_without_its_values(caplog, handler, field, subject):
    payload = {field: SENTINEL}
    with caplog.at_level(logging.WARNING, logger="external_references.consumer"):
        asyncio.run(handler(payload, subject))

    messages = [r.getMessage() for r in caplog.records]
    assert any(
        "reason=invalid_payload" in m and subject in m and field in m for m in messages
    ), messages
    assert all(SENTINEL not in m for m in messages)
