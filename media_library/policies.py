from saas_media_library import AssetKind, Visibility

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
    {"resource_type": "forms", "collection_name": "image", "kind": AssetKind.IMAGE, "visibility": Visibility.PUBLIC, "allowed_mime_types": IMAGE_MIME, "allow_multiple": False, "step_options": {"image_derive": {"formats": ["webp"], "sizes": [256, 512, 1024]}}},
    {"resource_type": "form_items", "collection_name": "image", "kind": AssetKind.IMAGE, "visibility": Visibility.RESTRICTED, "allowed_mime_types": IMAGE_MIME, "allow_multiple": False, "step_options": {"image_derive": {"formats": ["webp"], "sizes": [256, 512, 1024]}}},
    {"resource_type": "form_answers", "collection_name": "file", "kind": AssetKind.DOCUMENT, "visibility": Visibility.PRIVATE, "allowed_mime_types": ANSWER_FILE_MIME, "allow_multiple": False},
    {"resource_type": "forms", "collection_name": "image_batch", "kind": AssetKind.IMAGE_BATCH, "visibility": Visibility.PUBLIC, "allowed_mime_types": ZIP_MIME, "allow_multiple": False, "step_options": {"image_batch": {"formats": ["webp"], "sizes": [256, 512, 1024]}}},
    {"resource_type": "form_items", "collection_name": "image_batch", "kind": AssetKind.IMAGE_BATCH, "visibility": Visibility.RESTRICTED, "allowed_mime_types": ZIP_MIME, "allow_multiple": False, "step_options": {"image_batch": {"formats": ["webp"], "sizes": [256, 512, 1024]}}},
]
