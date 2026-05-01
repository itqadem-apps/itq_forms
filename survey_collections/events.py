from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from surveys.events import DomainEvent


@dataclass(slots=True)
class CollectionCreated(DomainEvent):
    aggregate_type: str = "collection"
    aggregate_id: int | str | None = None
    event: str = "CollectionCreated"
    collection: dict[str, Any] | None = None


@dataclass(slots=True)
class CollectionUpdated(DomainEvent):
    aggregate_type: str = "collection"
    aggregate_id: int | str | None = None
    event: str = "CollectionUpdated"
    collection: dict[str, Any] | None = None


@dataclass(slots=True)
class CollectionPublished(DomainEvent):
    aggregate_type: str = "collection"
    aggregate_id: int | str | None = None
    event: str = "CollectionPublished"
    collection: dict[str, Any] | None = None


@dataclass(slots=True)
class CollectionUnpublished(DomainEvent):
    aggregate_type: str = "collection"
    aggregate_id: int | str | None = None
    event: str = "CollectionUnpublished"
    collection: dict[str, Any] | None = None


@dataclass(slots=True)
class CollectionDeleted(DomainEvent):
    aggregate_type: str = "collection"
    aggregate_id: int | str | None = None
    event: str = "CollectionDeleted"
    collection: dict[str, Any] | None = None
