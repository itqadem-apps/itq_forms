from __future__ import annotations

import logging
from uuid import UUID

from surveys.models import Survey

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


def build_survey_payload_or_log(survey: Survey, event_name: str) -> dict | None:
    """Serialize *survey* and return the payload, or ``None`` if the
    survey is missing an organization id (in which case skip publish)."""
    payload = serialize_survey(survey)
    if payload["organization_id"]:
        return payload
    logger.warning(
        "Skipping survey event publish: reason=missing_organization_id survey_id=%s event=%s",
        survey.pk,
        event_name,
    )
    return None


def serialize_survey(survey: Survey) -> dict:
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
                "description": translation.description,
                "summary": translation.short_description,
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
