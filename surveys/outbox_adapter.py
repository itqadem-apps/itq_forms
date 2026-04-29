from __future__ import annotations

import dataclasses
from datetime import datetime
from enum import Enum
from typing import Any, Sequence
from uuid import UUID

from surveys.events import (
    AssessmentCreated,
    AssessmentDeleted,
    AssessmentPublished,
    AssessmentUnpublished,
    AssessmentUpdated,
)

_SUBJECT_TOKEN: dict[type, str] = {
    AssessmentCreated: "assessment.created",
    AssessmentUpdated: "assessment.updated",
    AssessmentPublished: "assessment.published",
    AssessmentUnpublished: "assessment.unpublished",
    AssessmentDeleted: "assessment.deleted",
}


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


class SurveysOutboxEventBus:
    """Django outbox bus that remaps assessment lifecycle subjects."""

    def __init__(self, outbox_repo) -> None:
        self._outbox = outbox_repo

    def publish(self, event) -> None:
        payload = _convert(dataclasses.asdict(event))
        aggregate_type = (
            _SUBJECT_TOKEN.get(type(event))
            or getattr(event, "aggregate_type", "")
            or type(event).__name__
        )
        aggregate_id = getattr(event, "aggregate_id", None)
        event_id = getattr(event, "event_id", None)
        occurred_at = getattr(event, "occurred_at", None)

        self._outbox.add(
            aggregate_type=aggregate_type,
            aggregate_id=str(aggregate_id) if aggregate_id else "",
            event_type=type(event).__name__,
            payload=payload,
            headers={"event_id": str(event_id) if event_id else ""},
            occurred_at=occurred_at,
        )

    def publish_many(self, events: Sequence) -> None:
        for event in events:
            self.publish(event)
