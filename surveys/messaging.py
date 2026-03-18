from __future__ import annotations

from django.conf import settings

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


def serialize_assessment(survey: Survey) -> dict:
    return {
        "id": str(survey.pk),
        "status": survey.status,
        "survey_type": survey.survey_type,
        "category_id": str(survey.category_id) if survey.category_id else None,
        "organization_id": None,
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
    event_bus.publish(
        AssessmentCreated(
            aggregate_id=survey.pk,
            assessment=serialize_assessment(survey),
        )
    )


def publish_assessment_updated(survey: Survey) -> None:
    event_bus.publish(
        AssessmentUpdated(
            aggregate_id=survey.pk,
            assessment=serialize_assessment(survey),
        )
    )


def publish_assessment_deleted(survey: Survey) -> None:
    event_bus.publish(
        AssessmentDeleted(
            aggregate_id=survey.pk,
            assessment=serialize_assessment(survey),
        )
    )


def publish_assessment_status_event(survey: Survey) -> None:
    payload = serialize_assessment(survey)
    if survey.status == Survey.STATUS_PUBLISHED:
        event_bus.publish(
            AssessmentPublished(
                aggregate_id=survey.pk,
                assessment=payload,
            )
        )
        return

    if survey.status in {Survey.STATUS_DRAFT, Survey.STATUS_ARCHIVED, Survey.STATUS_SUSPENDED}:
        event_bus.publish(
            AssessmentUnpublished(
                aggregate_id=survey.pk,
                assessment=payload,
            )
        )
        return

    event_bus.publish(
        AssessmentUpdated(
            aggregate_id=survey.pk,
            assessment=payload,
        )
    )