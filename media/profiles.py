"""What each forms upload slot accepts (`pkg_media.UploadProfile`).

These are forms' own definitions. The media resource policies they replaced
are retired; nothing in forms reads or syncs them.
"""
from __future__ import annotations

from pkg_media import AssetKind, ProcessingConfig, UploadProfile, Visibility

IMAGE_MIME = {"image/jpeg", "image/png", "image/webp"}

# Survey and collection thumbs and covers: catalog artwork, public.
FORMS_THUMB = UploadProfile(
    name="forms-thumb",
    kind=AssetKind.IMAGE,
    visibility=Visibility.PUBLIC,
    allowed_mime_types=IMAGE_MIME,
    max_size_bytes=2_000_000,
    processing_config=ProcessingConfig(
        step_options={"image_derive": {"formats": ["webp"], "sizes": [128, 256]}},
    ),
)

FORMS_COVER = UploadProfile(
    name="forms-cover",
    kind=AssetKind.IMAGE,
    visibility=Visibility.PUBLIC,
    allowed_mime_types=IMAGE_MIME,
    max_size_bytes=5_000_000,
    processing_config=ProcessingConfig(
        step_options={"image_derive": {"formats": ["webp"], "sizes": [256, 512, 1024]}},
    ),
)

# Section and question covers and option images: survey content, read through
# forms' resolve endpoints (media.access.can_access).
FORMS_ITEM_IMAGE = UploadProfile(
    name="forms-item-image",
    kind=AssetKind.IMAGE,
    visibility=Visibility.RESTRICTED,
    allowed_mime_types=IMAGE_MIME,
    processing_config=ProcessingConfig(
        step_options={"image_derive": {"formats": ["webp"], "sizes": [256, 512, 1024]}},
    ),
)

# A respondent's file for a file question (`UserAnswer.file_asset_id`). Opened
# by whoever may read that submission (`media.access`), never public.
FORMS_ANSWER_FILE = UploadProfile(
    name="forms-answer-file",
    kind=AssetKind.DOCUMENT,
    visibility=Visibility.RESTRICTED,
    allowed_mime_types={
        "image/jpeg",
        "image/png",
        "image/webp",
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/plain",
    },
    max_size_bytes=10_000_000,
)

UPLOAD_PROFILES = {p.name: p for p in (FORMS_THUMB, FORMS_COVER, FORMS_ITEM_IMAGE, FORMS_ANSWER_FILE)}
