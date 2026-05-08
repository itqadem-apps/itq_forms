"""Single entry point for emitting domain events.

Every call site that wants to publish a domain event calls ``publish(event)``.
This writes one row to the ``outbox`` table inside the current DB
transaction; the in-process relay (started by ASGI lifespan) forwards
the row to NATS.

The relay builds the final NATS subject as
``{OUTBOX_SUBJECT_PREFIX}.{aggregate_type}`` — so we stash the
registered subject *token* (e.g. ``"survey.created"``) into the
row's ``aggregate_type`` column. The original Python class name lives
in ``event_type``.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from unimessaging.outbox_django import DjangoOutboxRepository

from app.messaging.subjects import subject_token_for

_outbox = DjangoOutboxRepository()


def _convert(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {key: _convert(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_convert(value) for value in obj]
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    return obj


def publish(event) -> None:
    """Persist *event* to the outbox; the relay publishes to NATS."""
    payload = _convert(dataclasses.asdict(event))
    aggregate_id = getattr(event, "aggregate_id", None)
    event_id = getattr(event, "event_id", None)

    _outbox.add(
        aggregate_type=subject_token_for(type(event)),
        aggregate_id=str(aggregate_id) if aggregate_id is not None else "",
        event_type=type(event).__name__,
        payload=payload,
        headers={"event_id": str(event_id) if event_id else ""},
        occurred_at=getattr(event, "occurred_at", None),
    )
