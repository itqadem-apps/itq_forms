"""``python manage.py relay``: the one process that publishes forms' outbox.

forms:AD-26 fixes the shape. The loop is forms' own, never unimessaging's
standalone relay runner: ``DjangoOutboxRelay.process_batch`` calls
``run_until_complete``, so it runs synchronously on one event loop this command
creates and sets. Each pass runs inside ``transaction.atomic()``, because the
package's bare cursor would otherwise release the ``FOR UPDATE SKIP LOCKED``
claim under autocommit before the row is marked, and a second relay could
publish it again.

The broker only publishes: it declares FORMS (create-if-absent on start) and
binds no durable. Consumers run in their own command.
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import threading
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections, transaction
from unimessaging.broker.broker import UnifiedMessageBroker
from unimessaging.broker.registry import HandlerRegistry
from unimessaging.outbox_django.relay import DjangoOutboxRelay

from app import messaging_contract as contract

logger = logging.getLogger(__name__)


class PayloadPassthrough:
    """Publish target that undoes ``DjangoOutboxRelay``'s second encode.

    Django's psycopg connection returns jsonb as text, so the relay's
    ``json.dumps(row["payload"])`` turns the payload into a JSON string
    literal. The payload column only ever holds an object, so a ``str`` after
    one decode means the text is the real payload and is published as-is.
    The package bug is reported, not fixed here.
    """

    def __init__(self, client) -> None:
        self._client = client

    async def publish(self, subject, data, headers=None):
        try:
            decoded = json.loads(data)
        except (TypeError, ValueError):
            decoded = None
        if isinstance(decoded, str):
            data = decoded.encode()
        return await self._client.publish(subject, data, headers=headers)


def build_broker() -> UnifiedMessageBroker:
    return UnifiedMessageBroker(
        subjects=[],
        service_name=settings.SERVICE_NAME,
        url=settings.NATS_URL,
        enable_durable=settings.JETSTREAM_ENABLED,
        stream_name=contract.FORMS_STREAM_NAME,
        stream_subjects=contract.FORMS_STREAM_SUBJECTS,
        consumers=[],
        registry=HandlerRegistry(),
    )


def touch_heartbeat(path: str) -> None:
    Path(path).touch()


def run_pass(relay: DjangoOutboxRelay, batch_size: int, heartbeat_path: str) -> int:
    """One relay pass. Raises on failure, leaving the heartbeat untouched."""
    close_old_connections()
    with transaction.atomic():
        published = relay.process_batch(batch_size)
    touch_heartbeat(heartbeat_path)
    return published


def _bounded_stop(loop: asyncio.AbstractEventLoop, broker, timeout: float) -> None:
    # asyncio.wait, not wait_for: a stop that ignores cancellation must not
    # hang the shutdown (same reasoning as app/messaging/runtime.py::_bounded).
    task = loop.create_task(broker.stop())
    done, _ = loop.run_until_complete(asyncio.wait({task}, timeout=timeout))
    if not done:
        task.cancel()
        logger.warning("Timed out after %ss stopping the relay broker", timeout)
        return
    if not task.cancelled() and task.exception() is not None:
        logger.error("Error stopping the relay broker", exc_info=task.exception())


class Command(BaseCommand):
    help = "Publish the outbox to NATS as one process (forms:AD-26)."

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._stop = threading.Event()

    def request_stop(self, *_args) -> None:
        self._stop.set()

    def handle(self, *args, **options) -> None:
        if not settings.JETSTREAM_ENABLED:
            # The relay declares FORMS and relies on JetStream's Nats-Msg-Id
            # dedupe; core NATS would publish with neither.
            raise CommandError("relay needs JETSTREAM_ENABLED=true")
        batch_size = settings.OUTBOX_BATCH_SIZE
        poll_interval = settings.OUTBOX_POLL_INTERVAL
        heartbeat_path = settings.OUTBOX_RELAY_HEARTBEAT_PATH
        # A file left by the previous container would pass the startup probe
        # before this process has done any work.
        Path(heartbeat_path).unlink(missing_ok=True)

        previous = {
            sig: signal.signal(sig, self.request_stop)
            for sig in (signal.SIGTERM, signal.SIGINT)
        }
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        broker = build_broker()
        try:
            loop.run_until_complete(broker.start())
            relay = DjangoOutboxRelay(
                PayloadPassthrough(broker.client),
                subject_prefix=settings.OUTBOX_SUBJECT_PREFIX,
            )
            logger.info(
                "Outbox relay started (prefix=%s, batch=%s)",
                settings.OUTBOX_SUBJECT_PREFIX,
                batch_size,
            )
            while not self._stop.is_set():
                try:
                    published = run_pass(relay, batch_size, heartbeat_path)
                except Exception:
                    logger.exception("Outbox relay pass failed")
                    published = 0
                if published == 0:
                    self._stop.wait(poll_interval)
            logger.info("Outbox relay stopping")
        finally:
            try:
                _bounded_stop(loop, broker, settings.MESSAGING_STOP_TIMEOUT)
            finally:
                close_old_connections()
                asyncio.set_event_loop(None)
                loop.close()
                for sig, handler in previous.items():
                    signal.signal(sig, handler)
