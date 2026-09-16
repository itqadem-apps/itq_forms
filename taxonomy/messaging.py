"""Inbound taxonomy category events.

Contract (itq_taxonomy/docs/CATEGORY_EVENTS.md), with the parts that shape this
code called out:

* Subjects are `taxonomy.category.created`, `.updated` and `.deleted`. Forms
  binds the single-token wildcard `taxonomy.category.*` with one durable, so
  every operation on a category is ordered against the others (estate:AD-15).
  Forms consumes this stream; it never declares it (estate:AD-13).
* The event type is discriminated by field presence, not by a type field:
  CategoryCreated carries `path` + `assets_count`, CategoryUpdated carries
  `path_changed`, CategoryDeleted carries `hard`.
* `DomainEvent.to_payload()` unwraps single-field value objects, so
  `category_id`, `tree_id` and `path` arrive as bare strings and `translations`
  as a list of `{language, name, slug}`.
* Only CategoryCreated carries `tree_id`. Update and delete are matched by
  `category_id` against what we already hold.
* `occurred_at` is naive UTC on the wire and is the projection's watermark.

Tree filter: forms projects exactly one taxonomy tree, `settings.CATEGORY_TREE_ID`.
A create for any other tree is dropped. Updates and deletes carry no `tree_id`,
so they are filtered implicitly: forms only holds a category whose create passed
the filter. An update for a category we do not hold is *parked* rather than
dropped — it is either another tree's (harmless, it is never replayed because no
create will arrive) or its own create has not landed yet.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from asgiref.sync import sync_to_async
from django.conf import settings

from taxonomy import projection
from taxonomy.models import Category

logger = logging.getLogger(__name__)


def _configured_tree_id() -> UUID | None:
    raw = getattr(settings, "CATEGORY_TREE_ID", None)
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except (TypeError, ValueError):
        logger.error("CATEGORY_TREE_ID=%r is not a UUID; taxonomy events cannot be projected", raw)
        return None


def _as_uuid(value: Any) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


@sync_to_async
def _apply_created(category_id, tree_id, path, translations, occurred_at) -> None:
    applied = projection.upsert_category(
        category_id=category_id,
        tree_id=tree_id,
        path=path,
        translations=translations,
        occurred_at=occurred_at,
    )
    if applied:
        projection.replay_deferred(category_id=category_id, tree_id=tree_id)


@sync_to_async
def _apply_updated(category_id, payload, occurred_at) -> str:
    """Apply an update, or park it when its create has not arrived.

    Returns what happened, for the caller's log line.
    """
    existing = Category.objects.filter(category_id=category_id).first()

    if existing is None:
        # Either out-of-order (the create is still in flight) or another tree's
        # category, which we will never hold. Parking is safe for both: a parked
        # event is only ever replayed by a create that passed the tree filter.
        projection.park_update(
            category_id=category_id, payload=payload, occurred_at=occurred_at
        )
        return "parked"

    if existing.deleted_at is not None:
        # A tombstone. An update carries no tree_id, so applying it would
        # rehydrate a row with a placeholder tree. Park it instead: only a
        # create can legitimately restore the category, and the parked update
        # is replayed right after that create lands.
        projection.park_update(
            category_id=category_id, payload=payload, occurred_at=occurred_at
        )
        return "parked-on-tombstone"

    path = payload.get("path")
    projection.upsert_category(
        category_id=category_id,
        tree_id=existing.tree_id,
        path=str(path) if path else existing.path_text,
        translations=list(payload.get("translations") or []),
        occurred_at=occurred_at,
    )
    return "applied"


@sync_to_async
def _apply_deleted(category_id, occurred_at) -> None:
    projection.delete_category(category_id=category_id, occurred_at=occurred_at)


async def handle_category_event(payload: Any, subject: str) -> None:
    if not isinstance(payload, dict):
        logger.warning("taxonomy.category payload is not a mapping (subject=%s)", subject)
        return

    event_id = payload.get("event_id")

    aggregate_type = payload.get("aggregate_type")
    if aggregate_type is not None and aggregate_type != "category":
        logger.warning(
            "taxonomy.category ignored aggregate_type=%r event_id=%r", aggregate_type, event_id
        )
        return

    category_id = _as_uuid(payload.get("category_id"))
    if category_id is None:
        logger.warning(
            "taxonomy.category missing or invalid category_id event_id=%r subject=%s",
            event_id,
            subject,
        )
        return

    occurred_at = projection.parse_occurred_at(payload.get("occurred_at"))

    if "hard" in payload:
        await _apply_deleted(category_id, occurred_at)
        logger.info("CategoryDeleted projected: category_id=%s event_id=%r", category_id, event_id)
        return

    if "path_changed" in payload:
        outcome = await _apply_updated(category_id, payload, occurred_at)
        logger.info(
            "CategoryUpdated %s: category_id=%s event_id=%r", outcome, category_id, event_id
        )
        return

    if "path" in payload and "assets_count" in payload:
        configured = _configured_tree_id()
        if configured is None:
            logger.error(
                "CategoryCreated dropped: CATEGORY_TREE_ID is unset (category_id=%s event_id=%r)",
                category_id,
                event_id,
            )
            return

        tree_id = _as_uuid(payload.get("tree_id"))
        if tree_id is None:
            logger.warning(
                "CategoryCreated missing or invalid tree_id category_id=%s event_id=%r",
                category_id,
                event_id,
            )
            return

        if tree_id != configured:
            logger.debug(
                "CategoryCreated for tree_id=%s != CATEGORY_TREE_ID=%s; skipping (category_id=%s)",
                tree_id,
                configured,
                category_id,
            )
            return

        path = payload.get("path")
        if path is None:
            logger.warning(
                "CategoryCreated missing path category_id=%s event_id=%r", category_id, event_id
            )
            return

        await _apply_created(
            category_id,
            tree_id,
            str(path),
            list(payload.get("translations") or []),
            occurred_at,
        )
        logger.info(
            "CategoryCreated projected: category_id=%s event_id=%r", category_id, event_id
        )
        return

    logger.warning(
        "Unrecognized taxonomy.category payload shape (subject=%s event_id=%r keys=%s)",
        subject,
        event_id,
        sorted(payload.keys()),
    )
