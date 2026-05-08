"""Unified messaging runtime started by ASGI lifespan.

Boots all event consumers, the FORMS publisher, and the in-process
outbox relay in a single process. Subjects span three JetStream streams
(FORMS, USERS, ORDERS), so the runtime spins up one
``UnifiedMessageBroker`` per stream — all sharing the unimessaging
default registry that ``app.messaging.registry.register_handlers``
populates.

The relay drains the outbox table and publishes rows on the FORMS
broker, removing the need for a separate ``outbox_relay`` process.
"""

from __future__ import annotations

import asyncio
import logging

from django.conf import settings
from unimessaging.broker.broker import UnifiedMessageBroker
from unimessaging.broker.config import JetStreamConsumer

from app import messaging_contract as contract
from app.messaging import get_messaging, start_messaging, stop_messaging
from app.messaging.registry import register_handlers
from app.messaging.relay import run_relay_loop

logger = logging.getLogger(__name__)


_users_broker: UnifiedMessageBroker | None = None
_orders_broker: UnifiedMessageBroker | None = None
_relay_task: asyncio.Task | None = None
_handlers_registered = False


def _orders_consumers() -> list[JetStreamConsumer]:
    subjects = list(contract.ORDERS_EVENT_SUBJECTS)
    return [
        JetStreamConsumer(
            label="orders",
            subject=subject,
            durable=contract.order_durable_name(subject, subjects),
        )
        for subject in subjects
    ]


async def start_all() -> None:
    """Start every messaging consumer + the outbox relay for the service."""
    global _users_broker, _orders_broker, _relay_task, _handlers_registered

    if not _handlers_registered:
        register_handlers()
        _handlers_registered = True

    forms_consumers = [
        *contract.AUTH_CONSUMERS,
        *contract.EXTERNAL_REFERENCE_EVENT_CONSUMERS,
        *contract.RECOMMENDABLE_CONSUMERS,
    ]

    await start_messaging(
        subjects=["__forms_internal.none"],
        service_name=settings.SERVICE_NAME,
        url=settings.NATS_URL,
        enable_durable=settings.JETSTREAM_ENABLED,
        stream_name=contract.FORMS_STREAM_NAME,
        stream_subjects=contract.FORMS_STREAM_SUBJECTS,
        consumers=forms_consumers,
        pull_batch=settings.JETSTREAM_PULL_BATCH,
        pull_timeout=settings.JETSTREAM_PULL_TIMEOUT,
    )

    users_subjects = list(contract.USERS_CHILD_SUBJECTS)
    _users_broker = UnifiedMessageBroker(
        subjects=["__forms_users_internal.none"],
        service_name=settings.SERVICE_NAME,
        url=settings.NATS_URL,
        enable_durable=settings.JETSTREAM_ENABLED,
        stream_name=contract.USERS_CHILD_STREAM_NAME,
        stream_subjects=contract.USERS_CHILD_STREAM_SUBJECTS,
        consumers=contract.build_users_child_consumers(users_subjects),
        pull_batch=settings.JETSTREAM_PULL_BATCH,
        pull_timeout=settings.JETSTREAM_PULL_TIMEOUT,
    )
    await _users_broker.start()

    _orders_broker = UnifiedMessageBroker(
        subjects=["__forms_orders_internal.none"],
        service_name=settings.SERVICE_NAME,
        url=settings.NATS_URL,
        enable_durable=settings.JETSTREAM_ENABLED,
        stream_name=contract.ORDERS_STREAM_NAME,
        stream_subjects=contract.ORDERS_STREAM_SUBJECTS,
        consumers=_orders_consumers(),
        pull_batch=settings.JETSTREAM_PULL_BATCH,
        pull_timeout=settings.JETSTREAM_PULL_TIMEOUT,
    )
    await _orders_broker.start()

    forms_messaging = get_messaging()
    if forms_messaging is None:
        raise RuntimeError("FORMS messaging client unavailable; cannot start outbox relay")

    _relay_task = asyncio.create_task(
        run_relay_loop(
            forms_messaging,
            subject_prefix=settings.OUTBOX_SUBJECT_PREFIX,
            poll_interval=settings.OUTBOX_POLL_INTERVAL,
            batch_size=settings.OUTBOX_BATCH_SIZE,
        ),
        name="outbox-relay",
    )

    logger.info("Messaging runtime started: forms+users+orders+relay")


async def stop_all() -> None:
    global _users_broker, _orders_broker, _relay_task

    if _relay_task is not None:
        _relay_task.cancel()
        try:
            await _relay_task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Error stopping outbox relay")
        _relay_task = None

    if _orders_broker is not None:
        try:
            await _orders_broker.stop()
        except Exception:
            logger.exception("Error stopping orders broker")
        _orders_broker = None

    if _users_broker is not None:
        try:
            await _users_broker.stop()
        except Exception:
            logger.exception("Error stopping users broker")
        _users_broker = None

    try:
        await stop_messaging()
    except Exception:
        logger.exception("Error stopping forms broker")

    logger.info("Messaging runtime stopped")
