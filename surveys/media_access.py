"""Grant/revoke media library access for restricted survey assets."""
from __future__ import annotations

import logging
from typing import List

from surveys.models import Survey, Section, AnswerSchemaOption
from surveys.media_client import build_client

logger = logging.getLogger(__name__)


def _collect_restricted_asset_ids(survey_id: int) -> List[str]:
    """Collect all non-null asset IDs from a survey's sections and options."""
    asset_ids: list[str] = []

    sections = Section.objects.filter(survey_id=survey_id).values_list("cover_asset_id", flat=True)
    asset_ids.extend(aid for aid in sections if aid)

    options = (
        AnswerSchemaOption.objects
        .filter(answer_schema__question__section__survey_id=survey_id)
        .values_list("image_asset_id", flat=True)
    )
    asset_ids.extend(aid for aid in options if aid)

    return asset_ids


def grant_survey_access(survey_id: int, user_id: str) -> None:
    """Grant a user access to all restricted assets in a survey."""
    asset_ids = _collect_restricted_asset_ids(survey_id)
    if not asset_ids:
        return

    client = build_client()
    if client is None:
        logger.warning("Media library not configured, skipping access grant")
        return

    try:
        result = client.access.bulk_grant(asset_ids=asset_ids, user_id=user_id)
        logger.info(
            "Granted media access: survey_id=%s user_id=%s granted=%s failed=%s",
            survey_id, user_id, result.granted, result.failed,
        )
    finally:
        client.close()


def promote_survey_assets(survey_id: int) -> None:
    """Promote restricted survey assets to PUBLIC on publish."""
    asset_ids = _collect_restricted_asset_ids(survey_id)
    if not asset_ids:
        return

    client = build_client()
    if client is None:
        logger.warning("Media library not configured, skipping visibility promote")
        return

    try:
        from saas_media_library.models import Visibility

        result = client.assets.bulk_update_visibility(asset_ids, Visibility.PUBLIC)
        logger.info(
            "Promoted assets to PUBLIC: survey_id=%s updated=%s failed=%s",
            survey_id, result.updated, result.failed,
        )
    except Exception:
        logger.exception("Failed to promote survey assets: survey_id=%s", survey_id)
    finally:
        client.close()


def demote_survey_assets(survey_id: int) -> None:
    """Demote restricted survey assets to PRIVATE on unpublish."""
    asset_ids = _collect_restricted_asset_ids(survey_id)
    if not asset_ids:
        return

    client = build_client()
    if client is None:
        logger.warning("Media library not configured, skipping visibility demote")
        return

    try:
        from saas_media_library.models import Visibility

        result = client.assets.bulk_update_visibility(asset_ids, Visibility.PRIVATE)
        logger.info(
            "Demoted assets to PRIVATE: survey_id=%s updated=%s failed=%s",
            survey_id, result.updated, result.failed,
        )
    except Exception:
        logger.exception("Failed to demote survey assets: survey_id=%s", survey_id)
    finally:
        client.close()


def revoke_survey_access(survey_id: int, user_id: str) -> None:
    """Revoke a user's access to all restricted assets in a survey."""
    asset_ids = _collect_restricted_asset_ids(survey_id)
    if not asset_ids:
        return

    client = build_client()
    if client is None:
        logger.warning("Media library not configured, skipping access revoke")
        return

    try:
        result = client.access.bulk_revoke(asset_ids=asset_ids, user_id=user_id)
        logger.info(
            "Revoked media access: survey_id=%s user_id=%s revoked=%s",
            survey_id, user_id, result.revoked,
        )
    finally:
        client.close()
