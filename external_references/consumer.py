from __future__ import annotations

import hashlib
import logging
from typing import Any

from asgiref.sync import sync_to_async
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError as PydanticValidationError,
)

from accounts.models import User
from external_references.models import ExternalReference
from external_references.services import upsert_external_reference
from surveys.models import Usage

logger = logging.getLogger(__name__)


class ExternalReferencePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_service: str | None = None
    source_model: str | None = None
    source_id: str | int | None = None
    collection_id: int | None = None
    survey_id: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class ExternalEnrollmentPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_service: str | None = None
    source_model: str | None = None
    source_id: str | int | None = None
    user_id: str | None = None
    usage_limit: int | None = 1
    enrollment_id: str | int | None = None
    data: dict[str, Any] = Field(default_factory=dict)


def _source_service(payload_service: str | None, subject: str | None) -> str:
    service = str(payload_service or "").strip().lower()
    if service:
        return service
    if subject:
        return subject.split(".", 1)[0].strip().lower()
    return ""


def _text(value: object) -> str:
    return str(value or "").strip()


def _usage_limit(value: int | None) -> int:
    try:
        return max(int(1 if value is None else value), 0)
    except (TypeError, ValueError):
        return 1


def _entitlement_key(
    *,
    source_service: str,
    source_model: str,
    source_id: str,
    user_id: str,
    enrollment_id: str,
) -> str:
    raw = (
        f"{source_service}:{enrollment_id}"
        if enrollment_id
        else f"{source_service}:{source_model}:{source_id}:{user_id}"
    )
    if len(raw) <= 64:
        return raw
    return f"cur:{hashlib.sha256(raw.encode()).hexdigest()[:60]}"


def _ensure_local_user(user_id: str) -> User:
    user, _created = User.objects.get_or_create(
        id=user_id,
        defaults={
            "username": user_id,
            "email": "",
            "is_active": True,
        },
    )
    return user


def _upsert_reference(
    *,
    source_service: str,
    source_model: str,
    source_id: str,
    collection_id: int | None,
    survey_id: int | None,
    data: dict[str, Any],
) -> ExternalReference | None:
    return upsert_external_reference(
        source_service=source_service,
        source_model=source_model,
        source_id=source_id,
        collection_id=collection_id,
        survey_id=survey_id,
        data=data,
    )


def _grant_external_usage(
    *,
    source_service: str,
    source_model: str,
    source_id: str,
    user_id: str,
    usage_limit: int,
    enrollment_id: str,
) -> int:
    references = list(
        ExternalReference.objects.select_related("survey", "collection").filter(
            source_service=source_service,
            source_model=source_model,
            source_id=source_id,
            survey__isnull=False,
        )
    )
    if not references:
        logger.warning(
            "external enrollment skip source=%s:%s:%s user_id=%s reason=no_survey_reference",
            source_service,
            source_model,
            source_id,
            user_id,
        )
        return 0

    user = _ensure_local_user(user_id)
    order_id = _entitlement_key(
        source_service=source_service,
        source_model=source_model,
        source_id=source_id,
        user_id=user_id,
        enrollment_id=enrollment_id,
    )
    granted = 0
    for reference in references:
        usage, created = Usage.objects.get_or_create(
            user=user,
            survey=reference.survey,
            collection=reference.collection,
            order_id=order_id,
            defaults={
                "usage_limit": usage_limit,
                "used_count": 0,
            },
        )
        if not created and usage.usage_limit != usage_limit:
            usage.usage_limit = usage_limit
            usage.save(update_fields=["usage_limit", "updated_at"])
        granted += 1
    return granted


async def handle_external_reference_event(payload: dict[str, Any], subject: str | None = None) -> None:
    if not isinstance(payload, dict):
        return

    try:
        data = ExternalReferencePayload.model_validate(payload)
    except PydanticValidationError as exc:
        logger.warning(
            "external reference skip subject=%s reason=invalid_payload error=%s",
            subject,
            exc,
        )
        return
    source_service = _source_service(data.source_service, subject)
    source_model = _text(data.source_model).lower()
    source_id = _text(data.source_id)
    if not source_service or not source_model or not source_id:
        logger.warning(
            "external reference skip subject=%s reason=missing_source_identity",
            subject,
        )
        return

    reference = await sync_to_async(_upsert_reference, thread_sensitive=True)(
        source_service=source_service,
        source_model=source_model,
        source_id=source_id,
        collection_id=data.collection_id,
        survey_id=data.survey_id,
        data=data.data,
    )
    if reference is not None:
        logger.info("external reference upserted id=%s source=%s", reference.id, reference)


async def handle_external_enrollment_event(payload: dict[str, Any], subject: str | None = None) -> None:
    if not isinstance(payload, dict):
        return

    try:
        data = ExternalEnrollmentPayload.model_validate(payload)
    except PydanticValidationError as exc:
        logger.warning(
            "external enrollment skip subject=%s reason=invalid_payload error=%s",
            subject,
            exc,
        )
        return
    source_service = _source_service(data.source_service, subject)
    source_model = _text(data.source_model).lower()
    source_id = _text(data.source_id)
    user_id = _text(data.user_id)
    if not source_service or not source_model or not source_id or not user_id:
        logger.warning(
            "external enrollment skip subject=%s reason=missing_identity",
            subject,
        )
        return

    granted = await sync_to_async(_grant_external_usage, thread_sensitive=True)(
        source_service=source_service,
        source_model=source_model,
        source_id=source_id,
        user_id=user_id,
        usage_limit=_usage_limit(data.usage_limit),
        enrollment_id=_text(data.enrollment_id),
    )
    logger.info(
        "external enrollment processed source=%s:%s:%s user_id=%s granted=%s",
        source_service,
        source_model,
        source_id,
        user_id,
        granted,
    )
