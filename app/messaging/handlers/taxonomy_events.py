from __future__ import annotations

import logging

from taxonomy.messaging import handle_category_event

logger = logging.getLogger(__name__)


class TaxonomyCategoryEventSubscriber:
    """Subscribes to taxonomy.category.* events."""

    async def handle_message(self, payload: dict | str, subject: str) -> None:
        logger.info("Received taxonomy category event: subject=%s", subject)
        await handle_category_event(payload, subject)
