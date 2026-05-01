from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4


@dataclass(slots=True)
class DomainEvent:
    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    aggregate_type: str = ""
    aggregate_id: int | str | None = None
    organization_id: str | None = None
    metadata: dict[str, Any] | None = None
    event: str = ""


@dataclass(slots=True)
class SurveyCreated(DomainEvent):
    aggregate_type: str = "survey"
    aggregate_id: int | str | None = None
    event: str = "SurveyCreated"
    survey: dict[str, Any] | None = None


@dataclass(slots=True)
class SurveyUpdated(DomainEvent):
    aggregate_type: str = "survey"
    aggregate_id: int | str | None = None
    event: str = "SurveyUpdated"
    survey: dict[str, Any] | None = None


@dataclass(slots=True)
class SurveyPublished(DomainEvent):
    aggregate_type: str = "survey"
    aggregate_id: int | str | None = None
    event: str = "SurveyPublished"
    survey: dict[str, Any] | None = None


@dataclass(slots=True)
class SurveyUnpublished(DomainEvent):
    aggregate_type: str = "survey"
    aggregate_id: int | str | None = None
    event: str = "SurveyUnpublished"
    survey: dict[str, Any] | None = None


@dataclass(slots=True)
class SurveyDeleted(DomainEvent):
    aggregate_type: str = "survey"
    aggregate_id: int | str | None = None
    event: str = "SurveyDeleted"
    survey: dict[str, Any] | None = None
