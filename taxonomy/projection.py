"""Projection of itq_taxonomy's category events into forms' local tables.

Forms holds a *projection* of one taxonomy tree, not a copy it maintains. The
rules here are `estate:AD-15`'s: one durable carries every operation on a
category, so nothing guarantees a create is seen before the update or delete
that follows it, and every write is therefore guarded by the event's
`occurred_at` watermark.

Three cases itq_courses' equivalent handler does not cover are covered here,
because this story forbids inheriting them:

* an update that arrives before its create is parked and replayed, not dropped;
* a move rewrites the paths of the moved category's descendants, which taxonomy
  emits no event for;
* a delete tombstones the subtree, not just the named category, because one
  `CategoryDeleted` stands for the whole subtree.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable, Optional
from uuid import UUID, uuid4

from django.db import transaction

from taxonomy.models import Category, CategoryTranslation, DeferredCategoryEvent

logger = logging.getLogger(__name__)

# Taxonomy joins a category's ancestry with dots: "parent-slug.child-slug".
PATH_SEP = "."


def parse_occurred_at(value: Any) -> Optional[datetime]:
    """Parse the wire `occurred_at` (naive UTC) into a tz-aware datetime.

    Returns None when absent or unparseable. A None watermark is treated as
    "older than anything": it cannot clobber projected state or lift a
    tombstone, but it may still bootstrap a category never seen before.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _display_name(translations: Iterable[dict[str, Any]]) -> Optional[str]:
    """Pick the name shown in admin listings, preferring English then Arabic.

    `Category.name` is a convenience column for `__str__` and the facet label;
    the authoritative per-language strings live in CategoryTranslation.
    """
    by_lang = {
        str(t.get("language") or "").lower(): t.get("name")
        for t in translations
        if isinstance(t, dict)
    }
    for lang in ("en", "ar"):
        if by_lang.get(lang):
            return by_lang[lang]
    for name in by_lang.values():
        if name:
            return name
    return None


def _is_newer(incoming: Optional[datetime], watermark: Optional[datetime]) -> bool:
    """Does `incoming` supersede `watermark`?

    A missing incoming timestamp never supersedes anything. A missing watermark
    is superseded by any real timestamp.
    """
    if incoming is None:
        return False
    if watermark is None:
        return True
    return incoming >= watermark


@transaction.atomic
def upsert_category(
    *,
    category_id: UUID,
    tree_id: UUID,
    path: Optional[str],
    translations: list[dict[str, Any]],
    occurred_at: Optional[datetime],
) -> bool:
    """Project a CategoryCreated/CategoryUpdated. Returns True if it applied."""
    existing = Category.objects.filter(category_id=category_id).first()

    if existing is not None:
        has_state = existing.occurred_at is not None or existing.deleted_at is not None
        if has_state and not _is_newer(occurred_at, existing.occurred_at):
            logger.debug(
                "category %s: event occurred_at=%s not newer than watermark=%s; discarding",
                category_id,
                occurred_at,
                existing.occurred_at,
            )
            return False

    old_path = existing.path_text if existing is not None else None

    Category.objects.update_or_create(
        category_id=category_id,
        defaults={
            "tree_id": tree_id,
            "path_text": path,
            "name": _display_name(translations) or (existing.name if existing else None),
            "occurred_at": occurred_at,
            # A create/update newer than the tombstone restores the row
            # (estate:AD-15's conditional heal-on-republish).
            "deleted_at": None,
        },
    )

    CategoryTranslation.objects.filter(category_id=category_id).delete()
    CategoryTranslation.objects.bulk_create(
        [
            CategoryTranslation(
                id=uuid4(),
                category_id=category_id,
                language=t.get("language") or "",
                name=t.get("name"),
                slug=t.get("slug"),
            )
            for t in translations
            if isinstance(t, dict) and t.get("language")
        ]
    )

    if old_path and path and old_path != path:
        _rewrite_descendant_paths(old_path=old_path, new_path=path, occurred_at=occurred_at)

    return True


def _rewrite_descendant_paths(
    *, old_path: str, new_path: str, occurred_at: Optional[datetime]
) -> None:
    """Move a subtree.

    Taxonomy emits one `CategoryUpdated` for the category that moved and none
    for anything beneath it, so a descendant's stored path would keep naming
    the old parent and the facet tree would silently lose the branch. The
    descendants' own watermarks are deliberately left untouched: their state
    did not change, only their address, and advancing them would let this
    rewrite suppress a genuine later update to one of them.
    """
    prefix = old_path + PATH_SEP
    descendants = Category.objects.filter(path_text__startswith=prefix)
    moved = 0
    for descendant in descendants:
        suffix = descendant.path_text[len(prefix):]
        descendant.path_text = new_path + PATH_SEP + suffix
        descendant.save(update_fields=["path_text"])
        moved += 1
    if moved:
        logger.info("moved %d descendant(s) from %r to %r", moved, old_path, new_path)


@transaction.atomic
def delete_category(*, category_id: UUID, occurred_at: Optional[datetime]) -> bool:
    """Tombstone a category and everything beneath it.

    One `CategoryDeleted` stands for a whole subtree, and a tombstone rather
    than a row delete is what lets a delete that overtakes its create still
    suppress that create.

    A delete with no parseable `occurred_at` falls back to now(): between
    wrongly hiding a category and wrongly showing a deleted one, hiding is the
    safer bias, and a later create can always restore it.
    """
    effective = occurred_at or datetime.now(timezone.utc)

    existing = Category.objects.filter(category_id=category_id).first()
    if existing is None:
        # Delete before create: record the tombstone so the create it is racing
        # cannot resurrect the category. tree_id is unknown here; the row is
        # already tombstoned so no reader sees it, and a later create supplies
        # the real tree_id only if it is newer.
        Category.objects.create(
            category_id=category_id,
            tree_id=uuid4(),
            path_text=None,
            name=None,
            occurred_at=occurred_at,
            deleted_at=effective,
        )
        logger.info("category %s: tombstoned ahead of its create", category_id)
        return True

    if existing.deleted_at is None and not _is_newer(occurred_at, existing.occurred_at):
        # Only a stale delete against a *live* row is discarded. Re-tombstoning
        # an already-tombstoned row is harmless and keeps the subtree sweep
        # below idempotent.
        if occurred_at is not None:
            logger.debug(
                "category %s: delete occurred_at=%s older than watermark=%s; discarding",
                category_id,
                occurred_at,
                existing.occurred_at,
            )
            return False

    subtree = [existing]
    if existing.path_text:
        subtree.extend(
            Category.objects.filter(path_text__startswith=existing.path_text + PATH_SEP)
        )

    for row in subtree:
        row.deleted_at = effective
        if occurred_at is not None:
            row.occurred_at = occurred_at
        row.save(update_fields=["deleted_at", "occurred_at"])

    logger.info("category %s: tombstoned %d row(s)", category_id, len(subtree))
    return True


def park_update(*, category_id: UUID, payload: dict[str, Any], occurred_at: Optional[datetime]) -> None:
    """Hold an update whose category has not been created here yet."""
    DeferredCategoryEvent.objects.create(
        id=uuid4(),
        category_id=category_id,
        occurred_at=occurred_at,
        payload=payload,
    )
    logger.info("category %s: update parked pending its create", category_id)


def replay_deferred(*, category_id: UUID, tree_id: UUID) -> int:
    """Apply any parked updates for a category that has just been created.

    Applied oldest-first so the newest wins, and cleared either way: a parked
    event that loses to the watermark is spent, not worth keeping.
    """
    parked = list(
        DeferredCategoryEvent.objects.filter(category_id=category_id).order_by("occurred_at")
    )
    if not parked:
        return 0

    applied = 0
    for event in parked:
        payload = event.payload if isinstance(event.payload, dict) else {}
        path = payload.get("path")
        if upsert_category(
            category_id=category_id,
            tree_id=tree_id,
            path=str(path) if path else None,
            translations=list(payload.get("translations") or []),
            occurred_at=parse_occurred_at(payload.get("occurred_at")),
        ):
            applied += 1

    DeferredCategoryEvent.objects.filter(
        id__in=[event.id for event in parked]
    ).delete()
    logger.info(
        "category %s: replayed %d of %d parked update(s)", category_id, applied, len(parked)
    )
    return applied
