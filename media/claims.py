"""Claim-on-attach for the GraphQL inputs that take an asset id.

Media treats every service credential as the owner of every asset, so the id
columns are the only boundary between services: whatever forms stores, its
resolve endpoints serve. A new id is accepted only when the caller uploaded it
through forms (`POST /uploads`) with the slot's profile and claimed it
(`POST /uploads/{sessionId}/attach`). The id a row already holds stays valid
(stored ids are grandfathered), and null or empty clears the slot.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional
from uuid import UUID

from django.core.exceptions import ValidationError
from pkg_media import UploadProfile

from media.models import UploadRecord
from media.profiles import FORMS_ANSWER_FILE, FORMS_COVER, FORMS_ITEM_IMAGE, FORMS_THUMB

ARTWORK_SLOTS = {"thumb_id": FORMS_THUMB, "cover_id": FORMS_COVER}
SECTION_SLOTS = {"cover_asset_id": FORMS_ITEM_IMAGE}
QUESTION_SLOTS = {"cover_asset_id": FORMS_ITEM_IMAGE}
OPTION_SLOTS = {"image_asset_id": FORMS_ITEM_IMAGE}


def caller_id(info) -> str:
    """The caller's Keycloak subject, the `owner` its upload records carry."""
    return info.context.identity.subject_str


def is_claimed(owner: str, asset_id: str, profile: UploadProfile) -> bool:
    try:
        asset = UUID(str(asset_id))
    except ValueError:
        return False
    return UploadRecord.objects.filter(owner=owner, profile=profile.name, attached_asset_id=asset).exists()


def is_claimed_for_answer(owner: str, asset_id: str, user_survey_id: int, question_id: int) -> bool:
    """`asset_id` was uploaded and claimed by `owner` as an answer file for
    this attempt's question, so one attempt's file never lands on another."""
    try:
        asset = UUID(str(asset_id))
    except ValueError:
        return False
    records = UploadRecord.objects.filter(owner=owner, profile=FORMS_ANSWER_FILE.name, attached_asset_id=asset)
    return any(
        str(r.context.get("userSurveyId")) == str(user_survey_id)
        and str(r.context.get("questionId")) == str(question_id)
        for r in records
    )


def require_claimed(
    info,
    data: Mapping[str, Any],
    slots: Mapping[str, UploadProfile],
    instance: Optional[object] = None,
) -> None:
    """Refuse every asset id in `data` (an input's set fields) that the
    caller did not upload and claim for that slot. `instance` is the row being
    updated: the id it already holds is accepted as is."""
    errors = {}
    for field, profile in slots.items():
        value = data.get(field)
        if not value:
            continue
        if instance is not None and value == getattr(instance, field, None):
            continue
        if not is_claimed(caller_id(info), value, profile):
            errors[field] = [
                f"Asset {value} was not uploaded through forms by you; "
                f"upload it with profile {profile.name!r} and attach it first."
            ]
    if errors:
        raise ValidationError(errors)
