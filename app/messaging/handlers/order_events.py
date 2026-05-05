from __future__ import annotations

import logging

from survey_collections.order_messaging import handle_order_event as handle_collection_order_event
from surveys.order_messaging import handle_order_event as handle_survey_order_event

logger = logging.getLogger(__name__)


class OrderEventSubscriber:
    """Subscribes to orders.order events.

    The broker dispatches as ``(payload, subject)`` and drops JetStream
    headers, so the per-app handlers fall back to ``payload['event_type']``
    / ``payload['event']`` to determine the event type. Each line is then
    routed by SKU prefix: ``forms:Survey:`` lines are handled by the surveys
    app, ``forms:Collection:`` lines by the survey_collections app.
    """

    async def handle_message(self, payload: dict | str, subject: str) -> None:
        logger.info("Received order event: subject=%s", subject)
        meta = {"subject": subject}
        await handle_survey_order_event(payload, meta)
        await handle_collection_order_event(payload, meta)
