"""Public API for upserting ExternalReference rows.

External services emit their native events; this service does not get to
customize them. The pattern: a handler in ``app/messaging/handlers/`` knows
the shape of an upstream service's event, maps it to source identifiers +
local Survey/Collection ids, and calls :func:`aupsert_external_reference`.

The upsert is idempotent on
``(source_service, source_model, source_id, collection, survey)``.
"""

from __future__ import annotations

import logging
from typing import Any

from asgiref.sync import sync_to_async

from survey_collections.models import SurveyCollection
from surveys.models import Survey

from external_references.models import ExternalReference

logger = logging.getLogger(__name__)


def upsert_external_reference(
    *,
    source_service: str,
    source_model: str,
    source_id: str,
    survey_id: int | None = None,
    collection_id: int | None = None,
    data: dict[str, Any] | None = None,
) -> ExternalReference | None:
    """Create or update a single ExternalReference row.

    Returns the row, or ``None`` if it could not be created (missing local
    target, or the referenced Survey/SurveyCollection was not found). The
    function logs a warning in those cases — handlers can ignore the return
    value if they don't care about the outcome.
    """
    source_service = (source_service or "").strip().lower()
    source_model = (source_model or "").strip().lower()
    source_id = str(source_id or "").strip()

    if not source_service or not source_model or not source_id:
        logger.warning(
            "external reference skip reason=missing_source_identity "
            "service=%r model=%r id=%r",
            source_service, source_model, source_id,
        )
        return None

    if collection_id is None and survey_id is None:
        logger.warning(
            "external reference skip source=%s:%s:%s reason=missing_local_target",
            source_service, source_model, source_id,
        )
        return None

    collection = None
    if collection_id is not None:
        collection = SurveyCollection.objects.filter(pk=collection_id).first()
        if collection is None:
            logger.warning(
                "external reference skip source=%s:%s:%s reason=missing_collection collection_id=%s",
                source_service, source_model, source_id, collection_id,
            )
            return None

    survey = None
    if survey_id is not None:
        survey = Survey.objects.filter(pk=survey_id).first()
        if survey is None:
            logger.warning(
                "external reference skip source=%s:%s:%s reason=missing_survey survey_id=%s",
                source_service, source_model, source_id, survey_id,
            )
            return None

    reference, _ = ExternalReference.objects.update_or_create(
        source_service=source_service,
        source_model=source_model,
        source_id=source_id,
        collection=collection,
        survey=survey,
        defaults={"data": data or {}},
    )
    return reference


aupsert_external_reference = sync_to_async(upsert_external_reference, thread_sensitive=True)
