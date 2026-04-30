from __future__ import annotations

import logging

from surveys.order_messaging import handle_order_event

logger = logging.getLogger(__name__)


class OrderEventSubscriber:
    """Subscribes to orders.order events.

    The broker dispatches as ``(payload, subject)`` and drops JetStream
    headers, so ``handle_order_event`` falls back to ``payload['event_type']``
    / ``payload['event']`` to determine the event type.
    """

    async def handle_message(self, payload: dict | str, subject: str) -> None:
        logger.info("Received order event: subject=%s", subject)
        await handle_order_event(payload, {"subject": subject})
