from __future__ import annotations

import logging

from survey_collections.models import SurveyCollection

logger = logging.getLogger(__name__)


def serialize_collection(collection: SurveyCollection) -> dict:
    organization_id = (
        str(collection.organization_id) if collection.organization_id else None
    )
    return {
        "id": str(collection.pk),
        "status": collection.status,
        "type": collection.type,
        "category_id": str(collection.category_id) if collection.category_id else None,
        "organization_id": organization_id,
        "sponsor": collection.sponsor,
        "assessment_ids": list(
            collection.assessments.values_list("pk", flat=True)
        ),
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
            for price in collection.prices.all()
        ],
        "translations": [
            {
                "language": translation.language,
                "title": translation.title,
                "slug": translation.slug,
                "description": translation.description,
                "summary": translation.short_description,
            }
            for translation in collection.translations.all()
        ],
    }
