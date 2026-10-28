"""Claim in media every asset a live forms record already holds, once
(`media.asset_claims`; pkg_media `backfill_claims`).

Dry run by default: prints what it would claim. `--apply` claims it and
prints the report. Safe to re-run: done claims come back `already_claimed`.
"""
from __future__ import annotations

from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from pkg_media import backfill_claims

from media import asset_claims


class Command(BaseCommand):
    help = "Claim the media assets forms records hold (dry run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Claim them in media (default: dry run).")

    def handle(self, *args, apply: bool = False, **options):
        rows = list(asset_claims.backfill_rows())
        per_collection = Counter(row[4] for row in rows)
        per_record = Counter(r.split(":", 1)[1].split("/", 1)[0] for r in {row[1] for row in rows})
        out = self.stdout.write
        out(f"rows: {len(rows)}")
        out(f"distinct asset ids: {len({row[0] for row in rows})}")
        out(f"distinct refs: {len({row[1] for row in rows})}")
        out("refs per record type: " + ", ".join(f"{k}={v}" for k, v in sorted(per_record.items())))
        out("rows per collection: " + ", ".join(f"{k}={v}" for k, v in sorted(per_collection.items())))
        out(f"rows with an org: {sum(1 for row in rows if row[2])}, with a user: {sum(1 for row in rows if row[3])}")
        if not apply:
            out("dry run: nothing claimed (pass --apply to claim)")
            return
        client = asset_claims.build_client()
        if client is None:
            raise CommandError("media is not configured (MEDIA_GRPC_TARGET and the Keycloak client)")
        report = backfill_claims(client, rows)
        out(
            f"claimed: {report.claimed}, already_claimed: {report.already_claimed}, "
            f"not_found: {len(report.not_found)}, other: {report.other}, calls: {report.calls}, "
            f"retries: {report.retries}"
        )
        if report.not_found:
            out("not found: " + " ".join(str(i) for i in report.not_found))
