"""Register collection domain events against their subject tokens."""

from __future__ import annotations

from app.messaging.subjects import register
from survey_collections.events import (
    CollectionCreated,
    CollectionDeleted,
    CollectionPublished,
    CollectionUnpublished,
    CollectionUpdated,
)

register(CollectionCreated, "collection.created")
register(CollectionUpdated, "collection.updated")
register(CollectionPublished, "collection.published")
register(CollectionUnpublished, "collection.unpublished")
register(CollectionDeleted, "collection.deleted")
