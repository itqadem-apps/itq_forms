from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from saas_media_library import AssetKind, Visibility

from surveys.media_client import build_client

IMAGE_MIME = {"image/jpeg", "image/png", "image/webp"}
ZIP_MIME = {"application/zip", "application/x-zip-compressed"}

ANSWER_FILE_MIME = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain",
}

POLICIES: list[dict] = [
    {"resource_type": "surveys", "collection_name": "thumb", "kind": AssetKind.IMAGE,
     "visibility": Visibility.PUBLIC, "allowed_mime_types": IMAGE_MIME,
     "allow_multiple": False, "max_size_bytes": 2_000_000,
     "step_options": {"image_derive": {"formats": ["webp"], "sizes": [128, 256]}}},
    {"resource_type": "surveys", "collection_name": "cover", "kind": AssetKind.IMAGE,
     "visibility": Visibility.PUBLIC, "allowed_mime_types": IMAGE_MIME,
     "allow_multiple": False, "max_size_bytes": 5_000_000,
     "step_options": {"image_derive": {"formats": ["webp"], "sizes": [256, 512, 1024]}}},
    # Collections (curricula and the rest) carry the same two image slots a
    # survey does — same shapes, same limits — so their policies mirror the two
    # above rather than sharing them: `resource_type` is what scopes an asset to
    # a kind of record, and a curriculum's cover is not a survey's.
    {"resource_type": "collections", "collection_name": "thumb", "kind": AssetKind.IMAGE,
     "visibility": Visibility.PUBLIC, "allowed_mime_types": IMAGE_MIME,
     "allow_multiple": False, "max_size_bytes": 2_000_000,
     "step_options": {"image_derive": {"formats": ["webp"], "sizes": [128, 256]}}},
    {"resource_type": "collections", "collection_name": "cover", "kind": AssetKind.IMAGE,
     "visibility": Visibility.PUBLIC, "allowed_mime_types": IMAGE_MIME,
     "allow_multiple": False, "max_size_bytes": 5_000_000,
     "step_options": {"image_derive": {"formats": ["webp"], "sizes": [256, 512, 1024]}}},
    {"resource_type": "forms", "collection_name": "image", "kind": AssetKind.IMAGE, "visibility": Visibility.PUBLIC,
     "allowed_mime_types": IMAGE_MIME, "allow_multiple": False,
     "step_options": {"image_derive": {"formats": ["webp"], "sizes": [256, 512, 1024]}}},
    {"resource_type": "form_items", "collection_name": "image", "kind": AssetKind.IMAGE,
     "visibility": Visibility.RESTRICTED, "allowed_mime_types": IMAGE_MIME, "allow_multiple": False,
     "step_options": {"image_derive": {"formats": ["webp"], "sizes": [256, 512, 1024]}}},
    {"resource_type": "form_answers", "collection_name": "file", "kind": AssetKind.DOCUMENT,
     "visibility": Visibility.PRIVATE, "allowed_mime_types": ANSWER_FILE_MIME, "allow_multiple": False},
    {
        "resource_type": "forms",
        "collection_name": "image_batch",
        "kind": AssetKind.IMAGE_BATCH,
        "visibility": Visibility.PUBLIC,
        "allowed_mime_types": ZIP_MIME,
        "allow_multiple": False,
        "step_options": {
            "zip_image_extract": {
                "allowed_extensions": [".jpg", ".jpeg", ".png", ".webp"],
                "auto_process_children": True,
            },
        }
    },
    {
        "resource_type": "form_items",
        "collection_name": "image_batch",
        "kind": AssetKind.IMAGE_BATCH,
        "visibility": Visibility.RESTRICTED,
        "allowed_mime_types": ZIP_MIME,
        "allow_multiple": False,
        "step_options": {
            "zip_image_extract": {
                "allowed_extensions": [".jpg", ".jpeg", ".png", ".webp"],
                "auto_process_children": True,
            },
        }
    },
]


class Command(BaseCommand):
    help = "Upsert media library resource policies (init container entry point)."

    def handle(self, *args, **options):
        client = build_client()
        if client is None:
            raise CommandError(
                "MEDIA_LIBRARY_URL/MEDIA_LIBRARY_TENANT_ID not configured"
            )
        try:
            results = client.policies.sync_policies(POLICIES)
        finally:
            client.close()
        self.stdout.write(self.style.SUCCESS(f"Synced {len(results)} policies"))
