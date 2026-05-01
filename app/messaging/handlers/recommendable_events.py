from __future__ import annotations

import logging

from app.messaging.handlers.courses_events import handle_courses_event
from recommendations.consumer import handle_recommendable_event

logger = logging.getLogger(__name__)


class RecommendableEventSubscriber:
    """Subscribes to courses/videos/articles/reservations events to maintain the catalog."""

    async def handle_message(self, payload: dict | str, subject: str) -> None:
        logger.info("Received recommendable event: subject=%s", subject)
        await handle_recommendable_event(payload, subject)
        # Course lifecycle events also drive ExternalReference + SurveyCollection state.
        # Single durable, two side effects (registry routes one handler per subject).
        if subject.startswith("courses.course."):
            await handle_courses_event(payload, subject)
