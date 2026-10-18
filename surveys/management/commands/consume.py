"""``python manage.py consume``: the one process that binds forms' durables.

forms:AD-26 fixes the shape. Every handler is registered, then the FORMS,
users, orders and taxonomy brokers bind all 11 durables with their estate:AD-22
limits and declare no stream. The heartbeat is touched from the brokers' own
ticks (``AllBrokersTicked``), never from a timer of its own. SIGTERM/SIGINT
stop the command, each broker bounded by ``MESSAGING_STOP_TIMEOUT``.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from app.messaging import runtime
from app.messaging.registry import register_handlers

logger = logging.getLogger(__name__)

STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT)


async def run_consumers(stop: asyncio.Event) -> None:
    # A file left by an earlier run must not pass the probe before this
    # process's brokers have ticked.
    Path(settings.CONSUMERS_HEARTBEAT_PATH).unlink(missing_ok=True)
    heartbeat = runtime.AllBrokersTicked(
        settings.CONSUMERS_HEARTBEAT_PATH, runtime.CONSUMER_BROKER_LABELS
    )
    await runtime.start_consumers(heartbeat)
    try:
        await stop.wait()
        logger.info("Consumers stopping")
    finally:
        await runtime.stop_consumers()


class Command(BaseCommand):
    help = "Bind every forms durable as one process (forms:AD-26)."

    def handle(self, *args, **options) -> None:
        if not settings.JETSTREAM_ENABLED:
            # No durable binds without JetStream, so no broker would ever tick
            # and the heartbeat would go stale with nothing logged.
            raise CommandError("consume needs JETSTREAM_ENABLED=true")
        register_handlers()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        stop = asyncio.Event()
        registered = []
        try:
            for sig in STOP_SIGNALS:
                loop.add_signal_handler(sig, stop.set)
                registered.append(sig)
            loop.run_until_complete(run_consumers(stop))
        finally:
            for sig in registered:
                loop.remove_signal_handler(sig)
            asyncio.set_event_loop(None)
            loop.close()
