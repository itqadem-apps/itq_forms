from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4


@dataclass(slots=True)
class DomainEvent:
    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    aggregate_type: str = ""
    aggregate_id: int | str | None = None
    metadata: dict[str, Any] | None = None
    event: str = ""


@dataclass(slots=True)
class AssessmentCreated(DomainEvent):
    aggregate_type: str = "assessment"
    aggregate_id: int | str | None = None
    event: str = "AssessmentCreated"
    assessment: dict[str, Any] | None = None


@dataclass(slots=True)
class AssessmentUpdated(DomainEvent):
    aggregate_type: str = "assessment"
    aggregate_id: int | str | None = None
    event: str = "AssessmentUpdated"
    assessment: dict[str, Any] | None = None


@dataclass(slots=True)
class AssessmentPublished(DomainEvent):
    aggregate_type: str = "assessment"
    aggregate_id: int | str | None = None
    event: str = "AssessmentPublished"
    assessment: dict[str, Any] | None = None


@dataclass(slots=True)
class AssessmentUnpublished(DomainEvent):
    aggregate_type: str = "assessment"
    aggregate_id: int | str | None = None
    event: str = "AssessmentUnpublished"
    assessment: dict[str, Any] | None = None


@dataclass(slots=True)
class AssessmentDeleted(DomainEvent):
    aggregate_type: str = "assessment"
    aggregate_id: int | str | None = None
    event: str = "AssessmentDeleted"
    assessment: dict[str, Any] | None = None
