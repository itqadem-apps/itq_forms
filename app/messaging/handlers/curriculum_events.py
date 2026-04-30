from __future__ import annotations

import logging

from curriculum_references.consumer import (
    handle_curriculum_enrollment_event,
    handle_curriculum_reference_event,
)

logger = logging.getLogger(__name__)


class CurriculumEventSubscriber:
    """Subscribes to *.curriculum_reference / *.curriculum_enrollment events."""

    async def handle_message(self, payload: dict | str, subject: str) -> None:
        logger.info("Received curriculum event: subject=%s", subject)
        if subject.endswith(".curriculum_enrollment"):
            await handle_curriculum_enrollment_event(payload, subject)
        else:
            await handle_curriculum_reference_event(payload, subject)