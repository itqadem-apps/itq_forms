from __future__ import annotations

import logging

from recommendations.consumer import handle_recommendable_event

logger = logging.getLogger(__name__)


class RecommendableEventSubscriber:
    """Subscribes to courses/videos/articles/reservations events to maintain the catalog."""

    async def handle_message(self, payload: dict | str, subject: str) -> None:
        logger.info("Received recommendable event: subject=%s", subject)
        await handle_recommendable_event(payload, subject)
