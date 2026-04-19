from __future__ import annotations

import logging
from typing import Any

from asgiref.sync import sync_to_async

from accounts.models import User

logger = logging.getLogger(__name__)


@sync_to_async
def _upsert_user(user: dict[str, Any]) -> tuple[User, bool]:
    user_id = str(user["id"])
    username = user.get("username") or user.get("email") or user_id
    defaults = {
        "email": user.get("email") or "",
        "username": username,
        "first_name": user.get("first_name") or "",
        "last_name": user.get("last_name") or "",
        "is_active": True,
    }
    return User.objects.update_or_create(id=user_id, defaults=defaults)


async def handle_auth_user_registered(payload: dict[str, Any], subject: str | None = None) -> None:
    user = payload.get("user") if isinstance(payload, dict) else None
    if not isinstance(user, dict) or not user.get("id"):
        logger.warning("auth.UserRegistered missing user.id; skipping")
        return

    saved, created = await _upsert_user(user)
    action = "created" if created else "updated"
    logger.info("Forms %s local user from auth.UserRegistered: %s", action, saved.id)
