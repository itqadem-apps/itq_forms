from __future__ import annotations

import json
import logging
from typing import Any, Mapping

from asgiref.sync import sync_to_async

from accounts.models import User
from surveys.models import Survey, Usage

logger = logging.getLogger(__name__)

_FORMS_SKU_PREFIX = "forms:Assessment:"


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


def _is_forms_line(line: object) -> bool:
    if not isinstance(line, Mapping):
        return False
    service_name = str(line.get("service_name") or "")
    sku = str(line.get("sku") or "")
    return service_name == "forms" or sku.startswith(_FORMS_SKU_PREFIX)


def _assessment_id_from_line(line: Mapping[str, Any]) -> int | None:
    sku = str(line.get("sku") or "")
    if not sku.startswith(_FORMS_SKU_PREFIX):
        return None
    raw_id = sku.removeprefix(_FORMS_SKU_PREFIX).strip()
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
def _ensure_local_user(user_id: str) -> User:
    return _ensure_local_user_sync(user_id)


@sync_to_async
def _grant_usage(*, user_id: str, order_id: str, survey_id: int, qty: int) -> bool:
    survey = Survey.objects.filter(pk=survey_id).first()
    if survey is None:
        logger.warning(
            "Skipping forms grant: reason=missing_survey order_id=%s survey_id=%s user_id=%s",
            order_id,
            survey_id,
            user_id,
        )
        return False

    user = _ensure_local_user_sync(user_id)
    usage, created = Usage.objects.get_or_create(
        user=user,
        survey=survey,
        order_id=order_id,
        defaults={
            "usage_limit": qty,
            "used_count": 0,
        },
    )
    if created:
        return True

    if usage.usage_limit != qty:
        usage.usage_limit = qty
        usage.save(update_fields=["usage_limit"])
    return False


@sync_to_async
def _revoke_usages(*, user_id: str, order_id: str, survey_ids: list[int]) -> int:
    if not survey_ids:
        return 0
    deleted, _details = Usage.objects.filter(
        user_id=user_id,
        order_id=order_id,
        survey_id__in=survey_ids,
    ).delete()
    return deleted


async def handle_order_event(
    payload: dict[str, Any] | str,
    meta: Mapping[str, Any] | None = None,
) -> None:
    data = _normalize_payload(payload)
    event_type = _event_type(data, meta)
    order = data.get("order")
    if not isinstance(order, Mapping):
        logger.warning("Skipping order event: reason=missing_order event_type=%s", event_type)
        return

    user_id = str(order.get("user_id") or "").strip()
    order_id = str(order.get("id") or "").strip()
    if not user_id or not order_id:
        logger.warning(
            "Skipping order event: reason=missing_order_identity event_type=%s order_id=%s user_id=%s",
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

    logger.debug("Ignoring order event: event_type=%s order_id=%s", event_type, order_id)


async def _grant_from_captured_order(order: Mapping[str, Any], *, user_id: str, order_id: str) -> None:
    lines = order.get("lines")
    if not isinstance(lines, list):
        return

    for line in lines:
        if not isinstance(line, Mapping) or not _is_forms_line(line):
            continue

        survey_id = _assessment_id_from_line(line)
        qty = _line_qty(line)
        if survey_id is None or qty <= 0:
            logger.warning(
                "Skipping forms grant line: reason=invalid_forms_line order_id=%s user_id=%s sku=%s qty=%s",
                order_id,
                user_id,
                line.get("sku"),
                line.get("qty"),
            )
            continue

        created = await _grant_usage(
            user_id=user_id,
            order_id=order_id,
            survey_id=survey_id,
            qty=qty,
        )
        logger.info(
            "Processed forms grant: order_id=%s user_id=%s survey_id=%s qty=%s created=%s",
            order_id,
            user_id,
            survey_id,
            qty,
            created,
        )


async def _revoke_from_full_refund(order: Mapping[str, Any], *, user_id: str, order_id: str) -> None:
    lines = order.get("lines")
    if not isinstance(lines, list):
        return

    survey_ids = []
    for line in lines:
        if not isinstance(line, Mapping) or not _is_forms_line(line):
            continue
        survey_id = _assessment_id_from_line(line)
        if survey_id is not None:
            survey_ids.append(survey_id)

    deleted = await _revoke_usages(user_id=user_id, order_id=order_id, survey_ids=survey_ids)
    logger.info(
        "Processed full refund revoke: order_id=%s user_id=%s surveys=%s deleted=%s",
        order_id,
        user_id,
        survey_ids,
        deleted,
    )


async def _revoke_from_line_refund(
    payload: Mapping[str, Any],
    *,
    user_id: str,
    order_id: str,
) -> None:
    line = payload.get("line")
    if not isinstance(line, Mapping) or not _is_forms_line(line):
        return

    survey_id = _assessment_id_from_line(line)
    if survey_id is None:
        logger.warning(
            "Skipping line refund revoke: reason=invalid_forms_line order_id=%s user_id=%s sku=%s",
            order_id,
            user_id,
            line.get("sku"),
        )
        return

    deleted = await _revoke_usages(user_id=user_id, order_id=order_id, survey_ids=[survey_id])
    logger.info(
        "Processed line refund revoke: order_id=%s user_id=%s survey_id=%s deleted=%s",
        order_id,
        user_id,
        survey_id,
        deleted,
    )
