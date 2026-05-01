"""In-process outbox relay started by ASGI lifespan.

Polls the ``outbox`` table and publishes each pending row to NATS via
the running FORMS broker. Handles both Postgres (``FOR UPDATE SKIP LOCKED``)
and SQLite (plain ``SELECT``) so it works in dev with the default
``db.sqlite3`` and in prod with Postgres.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from asgiref.sync import sync_to_async
from django.db import connection, transaction

logger = logging.getLogger(__name__)

DEFAULT_TABLE = "outbox"
DEFAULT_MAX_RETRIES = 10
DEFAULT_BASE_BACKOFF = 5  # seconds


@sync_to_async
def _claim_pending_ids(batch_size: int, table: str) -> list[int]:
    """Return up to *batch_size* PENDING outbox row ids, locking them on Postgres."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            if connection.vendor == "postgresql":
                cursor.execute(
                    f"""
                    SELECT id FROM {table}
                    WHERE status = 'PENDING' AND available_at <= now()
                    ORDER BY available_at
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                    """,
                    [batch_size],
                )
            else:
                cursor.execute(
                    f"""
                    SELECT id FROM {table}
                    WHERE status = 'PENDING' AND available_at <= CURRENT_TIMESTAMP
                    ORDER BY available_at
                    LIMIT %s
                    """,
                    [batch_size],
                )
            return [row[0] for row in cursor.fetchall()]


@sync_to_async
def _fetch_rows(ids: list[int], table: str) -> list[dict]:
    if not ids:
        return []
    placeholders = ",".join(["%s"] * len(ids))
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT * FROM {table} WHERE id IN ({placeholders})",
            ids,
        )
        columns = [col[0] for col in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

    for row in rows:
        if isinstance(row.get("payload"), str):
            row["payload"] = json.loads(row["payload"])
    return rows


@sync_to_async
def _mark_published(row_id: int, table: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {table}
            SET status='PUBLISHED', published_at=CURRENT_TIMESTAMP, last_error=NULL
            WHERE id=%s
            """,
            [row_id],
        )


@sync_to_async
def _mark_retry(
    row_id: int,
    *,
    retries: int,
    available_at: datetime,
    error: str,
    failed: bool,
    table: str,
) -> None:
    status = "FAILED" if failed else "PENDING"
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE {table}
            SET status=%s, retries=%s, available_at=%s, last_error=%s
            WHERE id=%s
            """,
            [status, retries, available_at, error, row_id],
        )


async def _process_batch(
    messaging,
    *,
    subject_prefix: str,
    batch_size: int,
    max_retries: int,
    base_backoff: int,
    table: str,
) -> int:
    ids = await _claim_pending_ids(batch_size, table)
    if not ids:
        return 0

    rows = await _fetch_rows(ids, table)
    published = 0
    for row in rows:
        try:
            subject = f"{subject_prefix}.{row['aggregate_type']}"
            data = json.dumps(row["payload"]).encode()
            await messaging.publish(subject, data)
            await _mark_published(row["id"], table)
            published += 1
        except Exception as exc:  # noqa: BLE001
            retries = int(row.get("retries") or 0) + 1
            delay = base_backoff * min(2 ** (retries - 1), 64)
            next_time = datetime.now(timezone.utc) + timedelta(seconds=delay)
            failed = retries >= max_retries
            await _mark_retry(
                row["id"],
                retries=retries,
                available_at=next_time,
                error=str(exc),
                failed=failed,
                table=table,
            )
            logger.warning(
                "Outbox row %s publish failed (retry %d): %s", row["id"], retries, exc
            )
    return published


async def run_relay_loop(
    messaging,
    *,
    subject_prefix: str,
    poll_interval: float,
    batch_size: int,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_backoff: int = DEFAULT_BASE_BACKOFF,
    table: str = DEFAULT_TABLE,
) -> None:
    """Run the relay forever. Cancel the task to stop."""
    logger.info("Outbox relay loop started (prefix=%s)", subject_prefix)
    try:
        while True:
            try:
                count = await _process_batch(
                    messaging,
                    subject_prefix=subject_prefix,
                    batch_size=batch_size,
                    max_retries=max_retries,
                    base_backoff=base_backoff,
                    table=table,
                )
                if count == 0:
                    await asyncio.sleep(poll_interval)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Outbox relay unexpected error")
                await asyncio.sleep(poll_interval)
    except asyncio.CancelledError:
        logger.info("Outbox relay loop cancelled")
        raise
