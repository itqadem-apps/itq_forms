"""Lifecycle handlers for ``courses.course.{created,updated,deleted}`` events.

The courses service emits its own events; this module adapts them into local
state. Each ``course`` becomes a local ``SurveyCollection(type="exam")``
linked via an ``ExternalReference``. Once the link exists, surveys can be
attached to the collection later.

All three handlers are idempotent on
``(source_service="courses", source_model="course", source_id=payload["id"])``.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import transaction

from external_references.models import ExternalReference
from survey_collections.models import SurveyCollection, SurveyCollectionTranslation

logger = logging.getLogger(__name__)

SOURCE_SERVICE = "courses"
SOURCE_MODEL = "course"


def _source_id(payload: dict[str, Any]) -> str:
    """Pull the canonical id from the event envelope.

    The cross-service contract uses ``aggregate_id``; ``id`` is accepted as a
    fallback for flatter payloads.
    """
    raw = payload.get("aggregate_id") or payload.get("id")
    return str(raw or "").strip()


def _entity(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the course attribute dict.

    Mirrors how this service publishes its own events (``SurveyCreated`` puts
    the entity under a ``survey`` key). The courses service is expected to
    use ``course``. Falls back to the envelope itself when no nested entity
    is present.
    """
    nested = payload.get("course")
    return nested if isinstance(nested, dict) else payload


def _organization_id(payload: dict[str, Any]):
    entity = _entity(payload)
    return entity.get("organization_id") or payload.get("organization_id") or None


def _apply_translations(collection: SurveyCollection, payload: dict[str, Any]) -> None:
    """Set/refresh collection translations from the course payload.

    The courses service publishes translations as a list of per-language
    dicts under ``course.translations``; mirror each into a
    ``SurveyCollectionTranslation``. Falls back to the legacy flat shape
    (top-level title/description/slug/language on ``course``) so tests and
    out-of-band ingest tools that send the simpler shape keep working.
    """
    entity = _entity(payload)

    translations = entity.get("translations")
    if isinstance(translations, list) and translations:
        for tr in translations:
            if not isinstance(tr, dict):
                continue
            title = tr.get("title")
            if not title:
                continue
            language = tr.get("language") or "en"
            description = tr.get("description")
            # Courses can publish description as a dict (e.g. {"text": "..."}).
            if isinstance(description, dict):
                description = (
                    description.get("text")
                    or description.get("body")
                    or description.get("content")
                    or None
                )
            SurveyCollectionTranslation.objects.update_or_create(
                collection=collection,
                language=language,
                defaults={
                    "title": title,
                    "description": description or None,
                    "short_description": tr.get("summary") or None,
                    "slug": tr.get("slug") or None,
                },
            )
        return

    title = entity.get("title") or payload.get("title")
    if not title:
        return
    language = entity.get("language") or payload.get("language") or "en"
    SurveyCollectionTranslation.objects.update_or_create(
        collection=collection,
        language=language,
        defaults={
            "title": title,
            "description": entity.get("description") or payload.get("description") or None,
            "short_description": entity.get("summary") or payload.get("summary") or None,
            "slug": entity.get("slug") or payload.get("slug") or None,
        },
    )


@transaction.atomic
def handle_course_created(payload: dict[str, Any]) -> ExternalReference | None:
    source_id = _source_id(payload)
    if not source_id:
        logger.warning("courses.course.created skip reason=missing_id payload_keys=%s", list(payload.keys()))
        return None

    ref = (
        ExternalReference.objects
        .select_related("collection")
        .filter(source_service=SOURCE_SERVICE, source_model=SOURCE_MODEL, source_id=source_id)
        .first()
    )
    if ref is not None and ref.collection_id is not None:
        ref.data = payload
        ref.save(update_fields=["data", "updated_at"])
        _apply_translations(ref.collection, payload)
        logger.info("courses.course.created reuse source_id=%s collection_id=%s", source_id, ref.collection_id)
        return ref

    collection = SurveyCollection.objects.create(
        type="exam",
        status=SurveyCollection.STATUS_DRAFT,
        organization_id=_organization_id(payload),
    )
    _apply_translations(collection, payload)

    if ref is not None:
        ref.collection = collection
        ref.data = payload
        ref.save(update_fields=["collection", "data", "updated_at"])
    else:
        ref = ExternalReference.objects.create(
            source_service=SOURCE_SERVICE,
            source_model=SOURCE_MODEL,
            source_id=source_id,
            collection=collection,
            data=payload,
        )

    logger.info("courses.course.created source_id=%s collection_id=%s", source_id, collection.pk)
    return ref


@transaction.atomic
def handle_course_updated(payload: dict[str, Any]) -> ExternalReference | None:
    source_id = _source_id(payload)
    if not source_id:
        logger.warning("courses.course.updated skip reason=missing_id")
        return None

    ref = (
        ExternalReference.objects
        .select_related("collection")
        .filter(source_service=SOURCE_SERVICE, source_model=SOURCE_MODEL, source_id=source_id)
        .first()
    )
    if ref is None or ref.collection_id is None:
        # Out-of-order delivery: create event lost or arrives later. Build it now.
        return handle_course_created(payload)

    ref.data = payload
    ref.save(update_fields=["data", "updated_at"])
    _apply_translations(ref.collection, payload)
    logger.info("courses.course.updated source_id=%s collection_id=%s", source_id, ref.collection_id)
    return ref


@transaction.atomic
def handle_course_deleted(payload: dict[str, Any]) -> int:
    source_id = _source_id(payload)
    if not source_id:
        logger.warning("courses.course.deleted skip reason=missing_id")
        return 0

    refs = ExternalReference.objects.filter(
        source_service=SOURCE_SERVICE, source_model=SOURCE_MODEL, source_id=source_id,
    )
    collection_ids = [c for c in refs.values_list("collection_id", flat=True) if c is not None]
    deleted_collections = 0
    if collection_ids:
        deleted_collections, _ = SurveyCollection.objects.filter(pk__in=collection_ids).delete()
        # Collection delete cascades to ExternalReference rows tied via FK.
    # Defensive: drop any reference rows that didn't have a collection FK.
    refs.delete()
    logger.info("courses.course.deleted source_id=%s deleted_collections=%s", source_id, deleted_collections)
    return deleted_collections
