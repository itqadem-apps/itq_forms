from __future__ import annotations

import logging
from typing import Any

from asgiref.sync import sync_to_async

from accounts.models import User, Child, ChildGuardian

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


def _child_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    child = payload.get("child") if isinstance(payload, dict) else None
    return child if isinstance(child, dict) else None


@sync_to_async
def _upsert_child(child: dict[str, Any]) -> None:
    child_id = child.get("id")
    if not child_id:
        return
    Child.objects.update_or_create(
        id=str(child_id),
        defaults={
            "name": child.get("name") or str(child_id),
            "photo_id": child.get("photo_id") or None,
            "status": child.get("status") or "active",
        },
    )


@sync_to_async
def _delete_child(child_id: str) -> None:
    Child.objects.filter(id=str(child_id)).delete()


@sync_to_async
def _upsert_child_guardian(guardian: dict[str, Any], payload: dict[str, Any]) -> None:
    relation_id = guardian.get("id") or payload.get("aggregate_id")
    child_id = guardian.get("child_id") or payload.get("child_id")
    user_id = guardian.get("user_id") or payload.get("user_id")
    if not relation_id or not child_id or not user_id:
        return

    child_defaults: dict[str, Any] = {"name": str(child_id)}
    child_payload = _child_payload(payload)
    if child_payload:
        child_defaults = {
            "name": child_payload.get("name") or str(child_id),
            "photo_id": child_payload.get("photo_id") or None,
            "status": child_payload.get("status") or "active",
        }
    child, _ = Child.objects.get_or_create(id=str(child_id), defaults=child_defaults)

    ChildGuardian.objects.update_or_create(
        id=str(relation_id),
        defaults={
            "child": child,
            "user_id": str(user_id),
            "status": str(guardian.get("status") or payload.get("status") or "active"),
            "role": str(guardian.get("role") or payload.get("role") or ""),
            "organization_id": guardian.get("organization_id") or payload.get("organization_id") or None,
        },
    )


@sync_to_async
def _mark_child_guardian_ended(relation_id: str | None, payload: dict[str, Any]) -> None:
    queryset = ChildGuardian.objects.all()
    if relation_id:
        queryset = queryset.filter(id=str(relation_id))
    else:
        child_id = payload.get("child_id")
        user_id = payload.get("user_id")
        if not child_id or not user_id:
            return
        queryset = queryset.filter(child_id=str(child_id), user_id=str(user_id))
    queryset.update(status="ended")


async def handle_child_event(payload: dict[str, Any], subject: str | None = None) -> None:
    if not isinstance(payload, dict):
        return

    event = str(payload.get("event") or "")
    child = _child_payload(payload)
    if event == "ChildProfileDeleted":
        child_id = payload.get("aggregate_id") or (child or {}).get("id")
        if child_id:
            await _delete_child(str(child_id))
        return

    if child:
        await _upsert_child(child)


async def handle_child_guardian_event(payload: dict[str, Any], subject: str | None = None) -> None:
    if not isinstance(payload, dict):
        return

    event = str(payload.get("event") or "")
    guardian = payload.get("guardian")
    guardian_payload = guardian if isinstance(guardian, dict) else {}

    if event == "GuardianRelationEnded":
        await _mark_child_guardian_ended(payload.get("aggregate_id"), payload)
        return

    await _upsert_child_guardian(guardian_payload, payload)
