from __future__ import annotations

import logging
from uuid import UUID

from unimessaging.outbox_django import DjangoOutboxEventBus, DjangoOutboxRepository

from surveys.events import (
    AssessmentCreated,
    AssessmentDeleted,
    AssessmentPublished,
    AssessmentUnpublished,
    AssessmentUpdated,
)
from surveys.models import Survey


event_bus = DjangoOutboxEventBus(DjangoOutboxRepository())
logger = logging.getLogger(__name__)


def _as_valid_uuid(value: object | None) -> str | None:
    if value is None:
        return None
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


def _resolve_organization_id(survey: Survey) -> str | None:
    survey_org = _as_valid_uuid(getattr(survey, "organization_id", None))
    if survey_org:
        return survey_org

    survey_org_obj = getattr(survey, "organization", None)
    if survey_org_obj is not None:
        org_obj_id = _as_valid_uuid(getattr(survey_org_obj, "id", None))
        if org_obj_id:
            return org_obj_id

    return None


def _build_payload_or_log(survey: Survey, event_name: str) -> dict | None:
    payload = serialize_assessment(survey)
    if payload["organization_id"]:
        return payload

    logger.warning(
        "Skipping assessment event publish: reason=missing_organization_id assessment_id=%s event=%s",
        survey.pk,
        event_name,
    )
    return None


def serialize_assessment(survey: Survey) -> dict:
    return {
        "id": str(survey.pk),
        "status": survey.status,
        "survey_type": survey.survey_type,
        "category_id": str(survey.category_id) if survey.category_id else None,
        "organization_id": _resolve_organization_id(survey),
        "is_for_child": survey.is_for_child,
        "is_timed": survey.is_timed,
        "is_evaluable": survey.is_evaluable,
        "display_option": survey.display_option,
        "prices": [
            {
                "currency": price.currency,
                "amount_cents": price.amount_cents,
                "compare_at_amount_cents": price.compare_at_amount_cents,
                "discounts": [
                    {
                        "type": discount.type,
                        "value": discount.value,
                        "code": discount.code,
                        "starts_at": discount.starts_at.isoformat() if discount.starts_at else None,
                        "ends_at": discount.ends_at.isoformat() if discount.ends_at else None,
                    }
                    for discount in price.discounts.all()
                ],
            }
            for price in survey.prices.all()
        ],
        "translations": [
            {
                "language": translation.language,
                "title": translation.title,
                "slug": translation.slug,
                "description": {
                    "text": translation.description,
                    "summary": translation.short_description,
                },
            }
            for translation in survey.translations.all()
        ],
        "metadata": {
            "use_score": survey.use_score,
            "use_classifications": survey.use_classifications,
            "use_recommendations": survey.use_recommendations,
            "use_actions": survey.use_actions,
        },
    }


def publish_assessment_created(survey: Survey) -> None:
    payload = _build_payload_or_log(survey, "AssessmentCreated")
    if payload is None:
        return

    event_bus.publish(
        AssessmentCreated(
            aggregate_id=survey.pk,
            organization_id=payload["organization_id"],
            assessment=payload,
        )
    )


def publish_assessment_updated(survey: Survey) -> None:
    payload = _build_payload_or_log(survey, "AssessmentUpdated")
    if payload is None:
        return

    event_bus.publish(
        AssessmentUpdated(
            aggregate_id=survey.pk,
            organization_id=payload["organization_id"],
            assessment=payload,
        )
    )


def publish_assessment_deleted(survey: Survey) -> None:
    payload = _build_payload_or_log(survey, "AssessmentDeleted")
    if payload is None:
        return

    event_bus.publish(
        AssessmentDeleted(
            aggregate_id=survey.pk,
            organization_id=payload["organization_id"],
            assessment=payload,
        )
    )


def publish_assessment_status_event(survey: Survey) -> None:
    event_name = "AssessmentPublished" if survey.status == Survey.STATUS_PUBLISHED else "AssessmentUnpublished"
    payload = _build_payload_or_log(survey, event_name)
    if payload is None:
        return

    if survey.status == Survey.STATUS_PUBLISHED:
        event_bus.publish(
            AssessmentPublished(
                aggregate_id=survey.pk,
                organization_id=payload["organization_id"],
                assessment=payload,
            )
        )
        return

    if survey.status in {Survey.STATUS_DRAFT, Survey.STATUS_ARCHIVED, Survey.STATUS_SUSPENDED}:
        event_bus.publish(
            AssessmentUnpublished(
                aggregate_id=survey.pk,
                organization_id=payload["organization_id"],
                assessment=payload,
            )
        )
        return

    event_bus.publish(
        AssessmentUpdated(
            aggregate_id=survey.pk,
            organization_id=payload["organization_id"],
            assessment=payload,
        )
    )
