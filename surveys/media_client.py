from __future__ import annotations

from django.conf import settings
from saas_media_library import MediaLibraryClient


def build_client() -> MediaLibraryClient | None:
    if not settings.MEDIA_LIBRARY_URL or not settings.MEDIA_LIBRARY_TENANT_ID:
        return None
    return MediaLibraryClient(
        base_url=settings.MEDIA_LIBRARY_URL,
        tenant_id=settings.MEDIA_LIBRARY_TENANT_ID,
        token=settings.MEDIA_LIBRARY_TOKEN or None,
    )
