from __future__ import annotations

import asyncio
import json
import signal
import time
from datetime import datetime, timedelta, timezone

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

from app import messaging_contract as contract
from unimessaging.broker.registry import HandlerRegistry
from unimessaging.outbox_django import DjangoOutboxRelay
from app.messaging import JetStreamConsumer, get_messaging, start_messaging, stop_messaging


class SqliteOutboxRelay:
    """SQLite-safe relay for local dev where SKIP LOCKED is unavailable."""

    def __init__(
        self,
        messaging,
        *,
        subject_prefix: str,
        table_name: str = "outbox",
        max_retries: int = 10,
        base_backoff: int = 5,
    ) -> None:
        self._messaging = messaging
        self._subject_prefix = subject_prefix
        self._table_name = table_name
        self._max_retries = max_retries
        self._base_backoff = base_backoff

    def _build_subject(self, aggregate_type: str) -> str:
        return f"{self._subject_prefix}.{aggregate_type}"

    def process_batch(self, batch_size: int = 50) -> int:
        loop = asyncio.get_event_loop()

        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT id
                FROM {self._table_name}
                WHERE status = 'PENDING' AND available_at <= CURRENT_TIMESTAMP
                ORDER BY available_at
                LIMIT %s
                """,
                [batch_size],
            )
            ids = [row[0] for row in cursor.fetchall()]
            if not ids:
                return 0

            placeholders = ",".join(["%s"] * len(ids))
            cursor.execute(
                f"SELECT * FROM {self._table_name} WHERE id IN ({placeholders})",
                ids,
            )
            columns = [col[0] for col in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

            published = 0
            for row in rows:
                try:
                    subject = self._build_subject(row["aggregate_type"])
                    data = json.dumps(row["payload"]).encode()
                    loop.run_until_complete(self._messaging.publish(subject, data))
                    cursor.execute(
                        f"""
                        UPDATE {self._table_name}
                        SET status = 'PUBLISHED',
                            published_at = CURRENT_TIMESTAMP,
                            last_error = NULL
                        WHERE id = %s
                        """,
                        [row["id"]],
                    )
                    published += 1
                except Exception as exc:
                    retries = int(row["retries"]) + 1
                    delay = self._base_backoff * min(2 ** (retries - 1), 64)
                    next_time = datetime.now(timezone.utc) + timedelta(seconds=delay)
                    status = "FAILED" if retries >= self._max_retries else "PENDING"
                    cursor.execute(
                        f"""
                        UPDATE {self._table_name}
                        SET status = %s,
                            retries = %s,
                            available_at = %s,
                            last_error = %s
                        WHERE id = %s
                        """,
                        [status, retries, next_time, str(exc), row["id"]],
                    )
            return published

def _consumer_handlers():
    from accounts.messaging import handle_auth_user_registered

    return {
        "auth.UserRegistered": handle_auth_user_registered,
    }


def _build_handler_registry(consumers: list[JetStreamConsumer]) -> HandlerRegistry | None:
    registry = HandlerRegistry()
    handlers = _consumer_handlers()
    attached = False
    for consumer in consumers:
        handler = handlers.get(consumer.subject)
        if handler is None:
            continue
        pattern = consumer.subject.replace(">", "*")
        registry.register_handler(pattern, handler)
        attached = True
    return registry if attached else None


def start_outbox_messaging(loop: asyncio.AbstractEventLoop) -> None:
    consumers = list(contract.AUTH_CONSUMERS)
    registry = _build_handler_registry(consumers)

    loop.run_until_complete(
        start_messaging(
            subjects=["__forms_internal.none"],
            service_name=settings.SERVICE_NAME,
            url=settings.NATS_URL,
            enable_durable=settings.JETSTREAM_ENABLED,
            stream_name=contract.FORMS_STREAM_NAME,
            stream_subjects=contract.FORMS_STREAM_SUBJECTS,
            consumers=consumers or None,
            pull_batch=settings.JETSTREAM_PULL_BATCH,
            pull_timeout=settings.JETSTREAM_PULL_TIMEOUT,
            registry=registry,
        )
    )


def build_outbox_relay(messaging, *, subject_prefix: str):
    relay_cls = SqliteOutboxRelay if connection.vendor == "sqlite" else DjangoOutboxRelay
    return relay_cls(messaging, subject_prefix=subject_prefix)


def count_outbox_rows(*, table_name: str = "outbox") -> dict[str, int]:
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT status, COUNT(*)
            FROM {table_name}
            WHERE (status = 'PENDING' AND available_at <= CURRENT_TIMESTAMP)
               OR status = 'FAILED'
            GROUP BY status
            """
        )
        counts = {"PENDING": 0, "FAILED": 0}
        counts.update({status: count for status, count in cursor.fetchall()})
        return counts


def reset_failed_outbox_rows(*, table_name: str = "outbox") -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {table_name}
            SET status = 'PENDING',
                retries = 0,
                available_at = CURRENT_TIMESTAMP,
                last_error = NULL
            WHERE status = 'FAILED'
            """
        )
        return cursor.rowcount


class Command(BaseCommand):
    help = "Run the unimessaging outbox relay for forms assessments"

    def add_arguments(self, parser):
        parser.add_argument(
            "--subject-prefix",
            default=settings.OUTBOX_SUBJECT_PREFIX,
            help='Prefix for published subjects (default: "forms")',
        )
        parser.add_argument(
            "--poll-interval",
            type=float,
            default=settings.OUTBOX_POLL_INTERVAL,
            help="Seconds to sleep when no pending rows are found",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=settings.OUTBOX_BATCH_SIZE,
            help="Max outbox rows to process per batch",
        )

    def handle(self, **options):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        start_outbox_messaging(loop)

        messaging = get_messaging()
        relay = build_outbox_relay(messaging, subject_prefix=options["subject_prefix"])

        running = True

        def _stop(sig, frame):
            nonlocal running
            running = False

        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)

        self.stdout.write(
            self.style.SUCCESS(
                f"Outbox relay started (prefix={options['subject_prefix']})"
            )
        )

        while running:
            try:
                count = relay.process_batch(options["batch_size"])
                if count == 0:
                    time.sleep(options["poll_interval"])
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"Relay error: {exc}"))
                time.sleep(options["poll_interval"])

        loop.run_until_complete(stop_messaging())
        loop.close()
        self.stdout.write(self.style.SUCCESS("Outbox relay stopped"))
