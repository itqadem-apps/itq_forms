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
