from __future__ import annotations

import logging

from external_references.consumer import (
    handle_external_enrollment_event,
    handle_external_reference_event,
)

logger = logging.getLogger(__name__)


class ExternalReferenceEventSubscriber:
    """Subscribes to *.external_reference / *.external_enrollment events."""

    async def handle_message(self, payload: dict | str, subject: str) -> None:
        logger.info("Received external reference event: subject=%s", subject)
        if subject.endswith(".external_enrollment"):
            await handle_external_enrollment_event(payload, subject)
        else:
            await handle_external_reference_event(payload, subject)
