from __future__ import annotations

import json
from pathlib import Path

from django.core.management import BaseCommand, CommandError

from surveys.media_client import build_client

DEFAULT_MAPPING = Path(__file__).resolve().parent.parent / "data" / "asset_mapping.json"


class Command(BaseCommand):
    help = "Delete cover and thumb assets from media library (DB + storage)."

    def add_arguments(self, parser):
        parser.add_argument(
            "path",
            nargs="?",
            default=None,
            help="Path to mapping.json (default: bundled asset_mapping.json).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be deleted without actually deleting.",
        )

    def handle(self, *args, **options):
        mapping_file = Path(options["path"]).resolve() if options["path"] else DEFAULT_MAPPING
        if not mapping_file.exists():
            raise CommandError(f"Mapping file not found at {mapping_file}")

        with open(mapping_file) as f:
            data = json.load(f)

        # Only covers and thumbs (resource_type=assessments)
        to_delete = [
            a for a in data.get("assets", [])
            if a["target"]["resource_type"] == "assessments"
        ]

        self.stdout.write(f"Found {len(to_delete)} cover/thumb assets to delete")

        if options["dry_run"]:
            for a in to_delete:
                self.stdout.write(
                    f"  Would delete: {a['uuid']} "
                    f"({a['target']['resource_type']}/{a['target']['collection_name']})"
                )
            return

        client = build_client()
        if client is None:
            raise CommandError("MEDIA_LIBRARY_URL/MEDIA_LIBRARY_TENANT_ID not configured")

        deleted = 0
        failed = 0
        try:
            for a in to_delete:
                asset_id = a["uuid"]
                try:
                    client.assets.delete(asset_id)
                    deleted += 1
                    self.stdout.write(f"  Deleted: {asset_id}")
                except Exception as e:
                    failed += 1
                    self.stderr.write(f"  Failed: {asset_id} — {e}")
        finally:
            client.close()

        self.stdout.write(self.style.SUCCESS(f"Done. Deleted: {deleted}, Failed: {failed}"))
