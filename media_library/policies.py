from saas_media_library import AssetKind, Visibility

IMAGE_MIME = {"image/jpeg", "image/png", "image/webp"}

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
    {
        "resource_type": "assessments",
        "collection_name": "cover",
        "kind": AssetKind.IMAGE,
        "visibility": Visibility.PUBLIC,
        "allowed_mime_types": IMAGE_MIME,
        "max_size_bytes": 5_000_000,
        "step_options": {
            "image_derive": {"formats": ["webp"], "sizes": [256, 512, 1024]},
        },
    },
    {
        "resource_type": "assessments",
        "collection_name": "thumb",
        "kind": AssetKind.IMAGE,
        "visibility": Visibility.PUBLIC,
        "allowed_mime_types": IMAGE_MIME,
        "max_size_bytes": 2_000_000,
        "step_options": {
            "image_derive": {"formats": ["webp"], "sizes": [128, 256]},
        },
    },
    {
        "resource_type": "assessment_sections",
        "collection_name": "cover",
        "kind": AssetKind.IMAGE,
        "visibility": Visibility.PUBLIC,
        "allowed_mime_types": IMAGE_MIME,
        "max_size_bytes": 5_000_000,
        "step_options": {
            "image_derive": {"formats": ["webp"], "sizes": [256, 512, 1024]},
        },
    },
    {
        "resource_type": "assessment_questions",
        "collection_name": "cover",
        "kind": AssetKind.IMAGE,
        "visibility": Visibility.RESTRICTED,
        "allowed_mime_types": IMAGE_MIME,
        "max_size_bytes": 5_000_000,
        "step_options": {
            "image_derive": {"formats": ["webp"], "sizes": [256, 512, 1024]},
        },
    },
    {
        "resource_type": "assessment_options",
        "collection_name": "image",
        "kind": AssetKind.IMAGE,
        "visibility": Visibility.RESTRICTED,
        "allowed_mime_types": IMAGE_MIME,
        "max_size_bytes": 5_000_000,
        "step_options": {
            "image_derive": {"formats": ["webp"], "sizes": [256, 512]},
        },
    },
    # User-submitted file answers. Private — only the submitter and graders
    # may resolve a download URL. Documents and images both allowed since
    # `with_file=True` MCQs and `QUESTION_TYPE_FILE` accept arbitrary uploads.
    {
        "resource_type": "assessment_answers",
        "collection_name": "file",
        "kind": AssetKind.DOCUMENT,
        "visibility": Visibility.PRIVATE,
        "allowed_mime_types": ANSWER_FILE_MIME,
        "max_size_bytes": 25_000_000,
    },
]
