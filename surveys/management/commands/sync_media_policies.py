from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from media_library.client import build_client
from media_library.policies import POLICIES


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
