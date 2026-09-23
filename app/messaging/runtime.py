"""Unified messaging runtime started by ASGI lifespan.

Boots all event consumers, the FORMS publisher, and the in-process
outbox relay in a single process. Subjects span three JetStream streams
(FORMS, USERS, ORDERS), so the runtime spins up one
``UnifiedMessageBroker`` per stream — all sharing the unimessaging
default registry that ``app.messaging.registry.register_handlers``
populates.

Only the FORMS broker declares a stream. Per ``estate:AD-13`` a stream is
declared by the one service that owns its subject prefix, and this service
owns ``forms.>`` only — ``USERS`` belongs to ``itq_users`` and ``ORDERS`` to
``itq_orders``. The other two brokers consume without declaring: a consumer
binds by subject and durable, and JetStream resolves the stream server-side,
so ``stream_name`` is not needed to read. Do not re-add it: ``add_stream``
does not reconcile an existing stream, it fails with BadRequestError 10058
and the package swallows that at debug, so a second declaration is settled
silently by boot order rather than reported.

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
_taxonomy_broker: UnifiedMessageBroker | None = None
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
    global _users_broker, _orders_broker, _taxonomy_broker, _relay_task, _handlers_registered

    if not _handlers_registered:
        register_handlers()
        _handlers_registered = True

    forms_consumers = [
        *contract.AUTH_CONSUMERS,
        *contract.EXTERNAL_REFERENCE_EVENT_CONSUMERS,
        *contract.RECOMMENDABLE_CONSUMERS,
    ]

    # No core-NATS subjects: everything this service consumes arrives on a
    # JetStream durable. The empty list used to need a placeholder because the
    # broker fell back to "notifications.>"; that fallback is gone.
    await start_messaging(
        subjects=[],
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
        subjects=[],
        service_name=settings.SERVICE_NAME,
        url=settings.NATS_URL,
        enable_durable=settings.JETSTREAM_ENABLED,
        # No stream_name/stream_subjects: itq_users owns USERS (estate:AD-13).
        consumers=contract.build_users_child_consumers(users_subjects),
        pull_batch=settings.JETSTREAM_PULL_BATCH,
        pull_timeout=settings.JETSTREAM_PULL_TIMEOUT,
    )
    await _users_broker.start()

    _orders_broker = UnifiedMessageBroker(
        subjects=[],
        service_name=settings.SERVICE_NAME,
        url=settings.NATS_URL,
        enable_durable=settings.JETSTREAM_ENABLED,
        # No stream_name/stream_subjects: itq_orders owns ORDERS (estate:AD-13).
        consumers=_orders_consumers(),
        pull_batch=settings.JETSTREAM_PULL_BATCH,
        pull_timeout=settings.JETSTREAM_PULL_TIMEOUT,
    )
    await _orders_broker.start()

    _taxonomy_broker = UnifiedMessageBroker(
        subjects=[],
        service_name=settings.SERVICE_NAME,
        url=settings.NATS_URL,
        enable_durable=settings.JETSTREAM_ENABLED,
        # No stream_name/stream_subjects: itq_taxonomy owns TAXONOMY (estate:AD-13).
        consumers=contract.TAXONOMY_CATEGORY_CONSUMERS,
        pull_batch=settings.JETSTREAM_PULL_BATCH,
        pull_timeout=settings.JETSTREAM_PULL_TIMEOUT,
    )
    await _taxonomy_broker.start()

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

    logger.info("Messaging runtime started: forms+users+orders+taxonomy+relay")


def _stop_timeout() -> float:
    return getattr(settings, "MESSAGING_STOP_TIMEOUT", 5.0)


async def _bounded(label: str, awaitable) -> None:
    """Wait for one shutdown step, but never longer than the budget.

    Every step here drains a NATS subscription, and a drain against a
    connection that has already gone away blocks rather than failing. The
    lifespan handler in ``app/asgi.py`` is what uvicorn waits on before a
    worker exits, and uvicorn imposes no deadline of its own, so one blocked
    drain kept the pod alive until Kubernetes force-killed it — long enough
    for ``kubectl rollout status`` to call the deploy failed while the new
    version was already serving (deploy-forms-r825n, v0.0.64).

    Deliberately ``asyncio.wait`` rather than ``asyncio.wait_for``: on timeout
    ``wait_for`` cancels the inner task and then *awaits* the cancellation, so
    a step that does not honour cancellation would hang anyway — which is the
    exact failure this is here to bound. Here the cancel is best-effort and
    unawaited, so the step returns inside the budget whatever it is doing.

    A shutdown step has nothing left to protect — the process is going away
    either way — so a timeout is logged and stepped over, never raised.
    """
    task = asyncio.ensure_future(awaitable)
    done, _ = await asyncio.wait({task}, timeout=_stop_timeout())
    if not done:
        task.cancel()  # best effort; not awaited, or we are back to hanging
        logger.warning(
            "Timed out after %ss stopping %s; abandoning it and continuing shutdown",
            _stop_timeout(),
            label,
        )
        return
    if task.cancelled():
        # ``Task.exception()`` re-raises for a cancelled task, and
        # CancelledError is a BaseException that would sail straight through
        # the lifespan handler's ``except Exception``. The relay task is always
        # cancelled by the time it gets here, so this is the normal path.
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Error stopping %s", label, exc_info=exc)


async def stop_all() -> None:
    global _users_broker, _orders_broker, _taxonomy_broker, _relay_task

    if _relay_task is not None:
        _relay_task.cancel()
        # Bounded like the rest: a task that swallows CancelledError would
        # hang the shutdown exactly as a stuck broker does.
        await _bounded("outbox relay", _relay_task)
        _relay_task = None

    for label, broker in (
        ("taxonomy broker", _taxonomy_broker),
        ("orders broker", _orders_broker),
        ("users broker", _users_broker),
    ):
        if broker is not None:
            await _bounded(label, broker.stop())
    _taxonomy_broker = _orders_broker = _users_broker = None

    await _bounded("forms broker", stop_messaging())

    logger.info("Messaging runtime stopped")
