"""Grant/revoke media library access for restricted survey assets.

Kept beside the resolve gate (media.views) while frontends still read media
directly: the per-user grants issued from `Usage`. `client.access` is HTTP-only,
so grants go through the HTTP client. Visibility is never pushed to media: the
resolve gate decides who reads a published survey's assets.
"""
from __future__ import annotations

import logging
from typing import List

from django.db.models import Q

from surveys.models import Survey, Section, Question, AnswerSchemaOption

from media.client import build_http_client

logger = logging.getLogger(__name__)


def _collect_restricted_asset_ids(survey_id: int) -> List[str]:
    """Collect all non-null asset IDs from a survey's sections, questions and options.

    Every caller of this -- grant, revoke -- acts on exactly the list it returns,
    so an asset omitted here is never granted to a buyer. It stays RESTRICTED
    with nobody holding a grant, which resolves as 403 for everyone read
    directly from media.

    Question covers were omitted. They are uploaded under the same profile as
    section covers and option images (forms-item-image, RESTRICTED) and belong
    here for the same reason.

    Deleted rows are read too (`all_objects`): a soft-deleted section, question or option
    (`forms:AD-21`) still shows in learner snapshots taken before the delete, so its asset is
    granted and revoked exactly as it was before the delete.
    """
    asset_ids: list[str] = []

    sections = Section.all_objects.filter(survey_id=survey_id).values_list("cover_asset_id", flat=True)
    asset_ids.extend(aid for aid in sections if aid)

    questions = (
        Question.all_objects
        # A sectionless (or flattened) question belongs by `survey_id` (`forms:AD-23`); a legacy
        # one with no `survey_id` still belongs through its section.
        .filter(Q(survey_id=survey_id) | Q(section__survey_id=survey_id))
        .values_list("cover_asset_id", flat=True)
    )
    asset_ids.extend(aid for aid in questions if aid)

    # `survey` is a real column on the option -- the chain this used to walk,
    # `answer_schema__question__section__survey_id`, names no field at all
    # (the FK is `schema`, not `answer_schema`), so every call raised FieldError
    # before it reached the media client.
    options = (
        AnswerSchemaOption.all_objects
        .filter(survey_id=survey_id)
        .values_list("image_asset_id", flat=True)
    )
    asset_ids.extend(aid for aid in options if aid)

    return asset_ids


def grant_survey_access(survey_id: int, user_id: str) -> None:
    """Grant a user access to all restricted assets in a survey."""
    asset_ids = _collect_restricted_asset_ids(survey_id)
    if not asset_ids:
        return

    client = build_http_client()
    if client is None:
        logger.warning("Media library not configured, skipping access grant")
        return

    result = client.access.bulk_grant(asset_ids=asset_ids, user_id=user_id)
    logger.info(
        "Granted media access: survey_id=%s user_id=%s granted=%s failed=%s",
        survey_id, user_id, result.granted, result.failed,
    )


def revoke_survey_access(survey_id: int, user_id: str) -> None:
    """Revoke a user's access to all restricted assets in a survey."""
    asset_ids = _collect_restricted_asset_ids(survey_id)
    if not asset_ids:
        return

    client = build_http_client()
    if client is None:
        logger.warning("Media library not configured, skipping access revoke")
        return

    result = client.access.bulk_revoke(asset_ids=asset_ids, user_id=user_id)
    logger.info(
        "Revoked media access: survey_id=%s user_id=%s revoked=%s",
        survey_id, user_id, result.revoked,
    )
