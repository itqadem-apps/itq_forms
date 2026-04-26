from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from asgiref.sync import sync_to_async

from recommendations.models import Recommendable

logger = logging.getLogger(__name__)


def _source_model(payload: dict[str, Any]) -> str:
    # Contract-first model typing: aggregate_type must be provided by producer.
    aggregate_type = payload.get("aggregate_type")
    if aggregate_type is None:
        return ""
    text = str(aggregate_type).strip()
    if not text:
        return ""
    return text.title()


def _source_id(payload: dict[str, Any]) -> str:
    # Contract-first identity: aggregate_id is the canonical source id.
    value = payload.get("aggregate_id")
    if value is None:
        return ""
    text = str(value).strip()
    return text


def _upsert_recommendable(service: str, model: str, source_id: str, payload: dict[str, Any], subject: str) -> None:
    data = dict(payload)
    data["subject"] = subject
    data["consumed_at"] = datetime.now(timezone.utc).isoformat()

    Recommendable.objects.update_or_create(
        source_service=service,
        source_model=model,
        source_id=source_id,
        defaults={"data": data},
    )


async def handle_recommendable_event(payload: dict[str, Any], subject: str) -> None:
    if not isinstance(payload, dict):
        return

    service = subject.split(".", 1)[0].strip().lower()
    if not service:
        return

    source_id = _source_id(payload)
    if not source_id:
        logger.warning("recommendable skip subject=%s reason=missing_aggregate_id", subject)
        return

    model = _source_model(payload)
    if not model:
        logger.warning("recommendable skip subject=%s reason=missing_aggregate_type", subject)
        return

    await sync_to_async(_upsert_recommendable, thread_sensitive=True)(
        service,
        model,
        source_id,
        payload,
        subject,
    )
    logger.info("recommendable upsert subject=%s source=%s:%s:%s", subject, service, model, source_id)
