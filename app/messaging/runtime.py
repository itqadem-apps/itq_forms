"""Unified messaging runtime started by ASGI lifespan.

Boots all event consumers required by the forms service in a single
process. Subjects span three JetStream streams (FORMS, USERS, ORDERS),
so the runtime spins up one ``UnifiedMessageBroker`` per stream — all
sharing the unimessaging default registry that
``app.messaging.registry.register_handlers`` populates.
"""

from __future__ import annotations

import logging

from django.conf import settings
from unimessaging.broker.broker import UnifiedMessageBroker
from unimessaging.broker.config import JetStreamConsumer

from app import messaging_contract as contract
from app.messaging import start_messaging, stop_messaging
from app.messaging.registry import register_handlers

logger = logging.getLogger(__name__)


_users_broker: UnifiedMessageBroker | None = None
_orders_broker: UnifiedMessageBroker | None = None
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
    """Start every messaging consumer for the service."""
    global _users_broker, _orders_broker, _handlers_registered

    if not _handlers_registered:
        register_handlers()
        _handlers_registered = True

    forms_consumers = [
        *contract.AUTH_CONSUMERS,
        *contract.CURRICULUM_EVENT_CONSUMERS,
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

    logger.info("Messaging runtime started: forms+users+orders")


async def stop_all() -> None:
    global _users_broker, _orders_broker

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
