from __future__ import annotations

import logging

from accounts.messaging import handle_auth_user_registered

logger = logging.getLogger(__name__)


class AuthEventSubscriber:
    """Subscribes to auth events and upserts local forms users."""

    async def handle_message(self, payload: dict | str, subject: str) -> None:
        logger.info("Received auth event: subject=%s", subject)
        if subject == "auth.UserRegistered":
            await handle_auth_user_registered(payload, subject)