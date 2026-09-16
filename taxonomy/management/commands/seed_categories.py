"""CAP-3 first fill: pull the configured tree from taxonomy's REST API once.

The projection's steady state is the event stream. This command exists only for
the moment before that: a freshly configured tree whose categories were created
before forms started consuming, and whose creates therefore sit behind a
retention window nobody can rely on. It is a one-off, run at deploy time — not
a sync, not a scheduler, and never on the request path.

Rows written here carry no `occurred_at`, which is deliberate: a seeded row is
"never projected from an event", so the very next real event for that category
wins outright instead of losing to a watermark this command invented.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from taxonomy import projection


class Command(BaseCommand):
    help = "Seed the local category projection from itq_taxonomy's REST API (one-off)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--api-url",
            default=None,
            help="Taxonomy API base URL (defaults to settings.TAXONOMY_API_URL).",
        )
        parser.add_argument(
            "--tree-id",
            default=None,
            help="Tree to seed (defaults to settings.CATEGORY_TREE_ID).",
        )
        parser.add_argument(
            "--timeout", type=float, default=30.0, help="HTTP timeout in seconds."
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and report what would be written, without writing.",
        )

    def handle(self, *args, **options):
        api_url = (options["api_url"] or settings.TAXONOMY_API_URL or "").rstrip("/")
        if not api_url:
            raise CommandError("No taxonomy API URL: set TAXONOMY_API_URL or pass --api-url.")

        tree_id_raw = options["tree_id"] or settings.CATEGORY_TREE_ID
        if not tree_id_raw:
            raise CommandError("No tree: set CATEGORY_TREE_ID or pass --tree-id.")
        try:
            tree_id = UUID(str(tree_id_raw))
        except (TypeError, ValueError):
            raise CommandError(f"Not a UUID: {tree_id_raw!r}")

        url = f"{api_url}/trees/{tree_id}/categories"
        self.stdout.write(f"Fetching {url}")
        try:
            with urllib.request.urlopen(url, timeout=options["timeout"]) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise CommandError(f"{url} returned HTTP {exc.code}: {exc.reason}")
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
            raise CommandError(f"Could not read {url}: {exc}")

        if not isinstance(body, list):
            raise CommandError(f"Expected a list of categories, got {type(body).__name__}")

        flat: list[dict[str, Any]] = []
        _flatten(body, flat)
        if not flat:
            self.stdout.write(self.style.WARNING("Tree has no categories; nothing to seed."))
            return

        if options["dry_run"]:
            for node in flat:
                self.stdout.write(f"  would seed {node.get('id')}  {node.get('path')}")
            self.stdout.write(f"{len(flat)} category(ies) would be seeded.")
            return

        written = 0
        for node in flat:
            category_id = node.get("id")
            path = node.get("path")
            if not category_id:
                continue
            projection.upsert_category(
                category_id=UUID(str(category_id)),
                tree_id=tree_id,
                path=str(path) if path else None,
                translations=list(node.get("translations") or []),
                # No watermark: see the module docstring.
                occurred_at=None,
            )
            written += 1

        self.stdout.write(self.style.SUCCESS(f"Seeded {written} category(ies) of tree {tree_id}."))


def _flatten(nodes: list[dict[str, Any]], out: list[dict[str, Any]]) -> None:
    """Walk the nested `children` the list endpoint returns for root categories."""
    for node in nodes:
        if not isinstance(node, dict):
            continue
        out.append(node)
        children = node.get("children")
        if isinstance(children, list):
            _flatten(children, out)
