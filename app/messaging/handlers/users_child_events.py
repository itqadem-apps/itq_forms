from __future__ import annotations

import logging

from accounts.messaging import handle_child_event, handle_child_guardian_event

logger = logging.getLogger(__name__)


class UsersChildEventSubscriber:
    """Subscribes to users.child.* and users.child_guardian.* events."""

    async def handle_message(self, payload: dict | str, subject: str) -> None:
        logger.info("Received users-child event: subject=%s", subject)
        if subject.startswith("users.child_guardian."):
            await handle_child_guardian_event(payload, subject)
        else:
            await handle_child_event(payload, subject)
