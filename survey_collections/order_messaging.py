from __future__ import annotations

import json
import logging
from typing import Any, Mapping

from asgiref.sync import sync_to_async
from pydantic import BaseModel, ConfigDict, Field

from accounts.models import User
from survey_collections.models import SurveyCollection
from surveys.models import Usage

logger = logging.getLogger(__name__)

_COLLECTION_SKU_PREFIX = "forms:Collection:"


class OrderLineModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sku: str | None = None
    service_name: str | None = None
    qty: int | None = None
    payment_state: str | None = None
    metadata: dict[str, Any] | None = Field(default_factory=dict)


class OrderBodyModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | int | None = None
    user_id: str | None = None
    payment_state: str | None = None
    lines: list[OrderLineModel] = Field(default_factory=list)
    metadata: dict[str, Any] | None = Field(default_factory=dict)


class OrderEventPayloadModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event_type: str | None = None
    event: str | None = None
    order: OrderBodyModel | None = None
    line: OrderLineModel | None = None
    metadata: dict[str, Any] | None = Field(default_factory=dict)


def _normalize_payload(payload: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        decoded = json.loads(payload)
        if isinstance(decoded, dict):
            return decoded
    raise ValueError("Order event payload must be a JSON object")


def _event_type(payload: Mapping[str, Any], meta: Mapping[str, Any] | None) -> str:
    headers = meta.get("headers") if isinstance(meta, Mapping) else None
    if isinstance(headers, Mapping):
        header_event = headers.get("event_type")
        if header_event:
            return str(header_event)
    return str(payload.get("event_type") or payload.get("event") or "")


def _is_collection_line(line: object) -> bool:
    if not isinstance(line, Mapping):
        return False
    sku = str(line.get("sku") or "")
    return sku.startswith(_COLLECTION_SKU_PREFIX)


def _collection_id_from_line(line: Mapping[str, Any]) -> int | None:
    sku = str(line.get("sku") or "")
    if not sku.startswith(_COLLECTION_SKU_PREFIX):
        return None
    raw_id = sku.removeprefix(_COLLECTION_SKU_PREFIX).strip()
    try:
        return int(raw_id)
    except (TypeError, ValueError):
        return None


def _line_qty(line: Mapping[str, Any]) -> int:
    try:
        return max(int(line.get("qty") or 0), 0)
    except (TypeError, ValueError):
        return 0


def _ensure_local_user_sync(user_id: str) -> User:
    user, _created = User.objects.get_or_create(
        id=user_id,
        defaults={
            "username": user_id,
            "email": "",
            "is_active": True,
        },
    )
    return user


@sync_to_async
def _grant_collection_usage(
    *,
    user_id: str,
    order_id: str,
    collection_id: int,
    qty: int,
) -> int:
    collection = (
        SurveyCollection.objects.prefetch_related("assessments")
        .filter(pk=collection_id)
        .first()
    )
    if collection is None:
        logger.warning(
            "Skipping collection grant: reason=missing_collection order_id=%s collection_id=%s user_id=%s",
            order_id,
            collection_id,
            user_id,
        )
        return 0

    surveys = list(collection.assessments.all())
    if not surveys:
        logger.warning(
            "Skipping collection grant: reason=empty_collection order_id=%s collection_id=%s user_id=%s",
            order_id,
            collection_id,
            user_id,
        )
        return 0

    user = _ensure_local_user_sync(user_id)
    granted = 0
    for survey in surveys:
        usage, created = Usage.objects.get_or_create(
            user=user,
            survey=survey,
            collection=collection,
            order_id=order_id,
            defaults={
                "usage_limit": qty,
                "used_count": 0,
            },
        )
        if not created and usage.usage_limit != qty:
            usage.usage_limit = qty
            usage.save(update_fields=["usage_limit", "updated_at"])
        granted += 1
    return granted


@sync_to_async
def _revoke_collection_usages(
    *,
    user_id: str,
    order_id: str,
    collection_ids: list[int],
) -> int:
    if not collection_ids:
        return 0
    deleted, _details = Usage.objects.filter(
        user_id=user_id,
        order_id=order_id,
        collection_id__in=collection_ids,
    ).delete()
    return deleted


async def handle_order_event(
    payload: dict[str, Any] | str,
    meta: Mapping[str, Any] | None = None,
) -> None:
    data = OrderEventPayloadModel.model_validate(_normalize_payload(payload)).model_dump(
        exclude_none=True
    )
    event_type = _event_type(data, meta)
    order = data.get("order")
    if not isinstance(order, Mapping):
        logger.warning(
            "Skipping collection order event: reason=missing_order event_type=%s",
            event_type,
        )
        return

    user_id = str(order.get("user_id") or "").strip()
    order_id = str(order.get("id") or "").strip()
    if not user_id or not order_id:
        logger.warning(
            "Skipping collection order event: reason=missing_order_identity event_type=%s order_id=%s user_id=%s",
            event_type,
            order_id or "<missing>",
            user_id or "<missing>",
        )
        return

    if event_type == "OrderPaymentCaptured":
        await _grant_from_captured_order(order, user_id=user_id, order_id=order_id)
        return

    if event_type == "OrderPaymentRefunded":
        await _revoke_from_full_refund(order, user_id=user_id, order_id=order_id)
        return

    if event_type == "OrderLinePaymentRefunded":
        await _revoke_from_line_refund(data, user_id=user_id, order_id=order_id)
        return

    logger.debug(
        "Ignoring collection order event: event_type=%s order_id=%s",
        event_type,
        order_id,
    )


async def _grant_from_captured_order(
    order: Mapping[str, Any], *, user_id: str, order_id: str
) -> None:
    lines = order.get("lines")
    if not isinstance(lines, list):
        return

    for line in lines:
        if not isinstance(line, Mapping) or not _is_collection_line(line):
            continue

        collection_id = _collection_id_from_line(line)
        qty = _line_qty(line)
        if collection_id is None or qty <= 0:
            logger.warning(
                "Skipping collection grant line: reason=invalid_collection_line order_id=%s user_id=%s sku=%s qty=%s",
                order_id,
                user_id,
                line.get("sku"),
                line.get("qty"),
            )
            continue

        granted = await _grant_collection_usage(
            user_id=user_id,
            order_id=order_id,
            collection_id=collection_id,
            qty=qty,
        )
        logger.info(
            "Processed collection grant: order_id=%s user_id=%s collection_id=%s qty=%s granted=%s",
            order_id,
            user_id,
            collection_id,
            qty,
            granted,
        )


async def _revoke_from_full_refund(
    order: Mapping[str, Any], *, user_id: str, order_id: str
) -> None:
    lines = order.get("lines")
    if not isinstance(lines, list):
        return

    collection_ids: list[int] = []
    for line in lines:
        if not isinstance(line, Mapping) or not _is_collection_line(line):
            continue
        collection_id = _collection_id_from_line(line)
        if collection_id is not None:
            collection_ids.append(collection_id)

    deleted = await _revoke_collection_usages(
        user_id=user_id, order_id=order_id, collection_ids=collection_ids
    )
    logger.info(
        "Processed collection full refund revoke: order_id=%s user_id=%s collections=%s deleted=%s",
        order_id,
        user_id,
        collection_ids,
        deleted,
    )


async def _revoke_from_line_refund(
    payload: Mapping[str, Any],
    *,
    user_id: str,
    order_id: str,
) -> None:
    line = payload.get("line")
    if not isinstance(line, Mapping) or not _is_collection_line(line):
        return

    collection_id = _collection_id_from_line(line)
    if collection_id is None:
        logger.warning(
            "Skipping collection line refund revoke: reason=invalid_collection_line order_id=%s user_id=%s sku=%s",
            order_id,
            user_id,
            line.get("sku"),
        )
        return

    deleted = await _revoke_collection_usages(
        user_id=user_id, order_id=order_id, collection_ids=[collection_id]
    )
    logger.info(
        "Processed collection line refund revoke: order_id=%s user_id=%s collection_id=%s deleted=%s",
        order_id,
        user_id,
        collection_id,
        deleted,
    )
