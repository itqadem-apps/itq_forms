from __future__ import annotations

import asyncio

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from app.messaging import get_messaging, stop_messaging
from surveys.management.commands.outbox_relay import (
    build_outbox_relay,
    count_outbox_rows,
    reset_failed_outbox_rows,
    start_outbox_messaging,
)


class Command(BaseCommand):
    help = "Send pending unimessaging outbox rows to NATS once, then exit"

    def add_arguments(self, parser):
        parser.add_argument(
            "--subject-prefix",
            default=settings.OUTBOX_SUBJECT_PREFIX,
            help='Prefix for published subjects (default: "forms")',
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=settings.OUTBOX_BATCH_SIZE,
            help="Max outbox rows to process per batch",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of messages to publish before exiting",
        )
        parser.add_argument(
            "--include-failed",
            action="store_true",
            help="Reset FAILED outbox rows to PENDING before publishing",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print pending/failed outbox counts without publishing",
        )

    def handle(self, **options):
        batch_size = options["batch_size"]
        limit = options["limit"]
        if batch_size <= 0:
            raise CommandError("--batch-size must be greater than 0")
        if limit is not None and limit <= 0:
            raise CommandError("--limit must be greater than 0")

        if options["dry_run"]:
            counts = count_outbox_rows()
            self.stdout.write(
                "Outbox dry run: "
                f"pending={counts['PENDING']} failed={counts['FAILED']}"
            )
            return

        if options["include_failed"]:
            reset_count = reset_failed_outbox_rows()
            self.stdout.write(f"Reset failed outbox rows: {reset_count}")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        published = 0
        messaging_started = False

        try:
            start_outbox_messaging(loop)
            messaging_started = True
            relay = build_outbox_relay(
                get_messaging(),
                subject_prefix=options["subject_prefix"],
            )

            while True:
                remaining = None if limit is None else limit - published
                if remaining is not None and remaining <= 0:
                    break

                current_batch_size = batch_size
                if remaining is not None:
                    current_batch_size = min(current_batch_size, remaining)

                count = relay.process_batch(current_batch_size)
                if count == 0:
                    break
                published += count
        finally:
            if messaging_started:
                loop.run_until_complete(stop_messaging())
            loop.close()

        self.stdout.write(self.style.SUCCESS(f"Published outbox rows: {published}"))
