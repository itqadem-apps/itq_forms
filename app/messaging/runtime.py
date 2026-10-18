"""Messaging runtime for ``manage.py consume`` (forms:AD-26).

Binds every durable forms consumes. Subjects span four JetStream streams
(FORMS, USERS, ORDERS, TAXONOMY), so the runtime starts one
``UnifiedMessageBroker`` per stream, all sharing the unimessaging default
registry that ``app.messaging.registry.register_handlers`` populates.

None of the four declares a stream. Per ``estate:AD-13`` a stream is
declared by the one service that owns its subject prefix: ``manage.py relay``
creates FORMS, and USERS, ORDERS and TAXONOMY belong to their owners. A
consumer binds by subject and durable, and JetStream resolves the stream
server-side, so ``stream_name`` is not needed to read. Do not add it:
``add_stream`` does not reconcile an existing stream, it fails with
BadRequestError 10058 and the package swallows that at debug, so a second
declaration is settled silently by boot order rather than reported.

Web runs none of this; it only writes outbox rows.
"""

from __future__ import annotations

import asyncio
import logging
from functools import partial
from pathlib import Path

from django.conf import settings
from unimessaging.broker.broker import UnifiedMessageBroker
from unimessaging.broker.config import JetStreamConsumer

from app import messaging_contract as contract

logger = logging.getLogger(__name__)


_consumer_brokers: list[tuple[str, UnifiedMessageBroker]] = []

CONSUMER_BROKER_LABELS = ("forms", "users", "orders", "taxonomy")


def _orders_consumers() -> list[JetStreamConsumer]:
    subjects = list(contract.ORDERS_EVENT_SUBJECTS)
    return [
        JetStreamConsumer(
            label="orders",
            subject=subject,
            durable=contract.order_durable_name(subject, subjects),
            limits=contract.DURABLE_LIMITS,
        )
        for subject in subjects
    ]


def _stop_timeout() -> float:
    return getattr(settings, "MESSAGING_STOP_TIMEOUT", 5.0)


async def _bounded(label: str, awaitable) -> None:
    """Wait for one shutdown step, but never longer than the budget.

    Every step here drains a NATS subscription, and a drain against a
    connection that has already gone away blocks rather than failing. An
    unbounded stop once kept a forms pod alive until Kubernetes force-killed
    it — long enough for ``kubectl rollout status`` to call the deploy failed
    while the new version was already serving (deploy-forms-r825n, v0.0.64).
    ``manage.py consume`` stops its brokers through this on SIGTERM.

    Deliberately ``asyncio.wait`` rather than ``asyncio.wait_for``: on timeout
    ``wait_for`` cancels the inner task and then *awaits* the cancellation, so
    a step that does not honour cancellation would hang anyway — which is the
    exact failure this is here to bound. Here the cancel is best-effort and
    unawaited, so the step returns inside the budget whatever it is doing.

    A shutdown step has nothing left to protect — the process is going away
    either way — so a timeout is logged and stepped over, never raised.
    """
    # One line per step, on entry. The next step's line timestamps how long
    # this one took — enough to locate a slow step from the pod
    # log alone, which is the only view available without cluster access.
    logger.info("Stopping %s", label)
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
        # a caller's ``except Exception``.
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Error stopping %s", label, exc_info=exc)


class AllBrokersTicked:
    """Heartbeat for ``manage.py consume``, driven only by broker ticks.

    Each broker's pull loop calls ``tick(label)`` once per fetch iteration.
    The file is touched only once every label has ticked since the previous
    touch, so one stalled broker lets it go stale however busy the others are.
    """

    def __init__(self, path: str, labels) -> None:
        self.path = Path(path)
        self.labels = frozenset(labels)
        self._ticked: set[str] = set()

    def tick(self, label: str) -> None:
        self._ticked.add(label)
        if self._ticked >= self.labels:
            self._ticked.clear()
            self.path.touch()


def _consumer_broker(consumers, on_tick) -> UnifiedMessageBroker:
    # No stream_name/stream_subjects on any of the four: only the relay
    # declares FORMS, and USERS/ORDERS/TAXONOMY belong to their owners
    # (estate:AD-13).
    return UnifiedMessageBroker(
        subjects=[],
        service_name=settings.SERVICE_NAME,
        url=settings.NATS_URL,
        enable_durable=settings.JETSTREAM_ENABLED,
        consumers=consumers,
        pull_batch=settings.JETSTREAM_PULL_BATCH,
        pull_timeout=settings.JETSTREAM_PULL_TIMEOUT,
        on_tick=on_tick,
    )


async def start_consumers(heartbeat: AllBrokersTicked) -> None:
    """Start the four consumer brokers that bind all of forms' durables.

    The FORMS broker is built directly rather than through ``start_messaging``,
    so it neither declares FORMS nor becomes the module-level publish broker.
    """
    global _consumer_brokers

    consumer_sets = {
        "forms": [
            *contract.AUTH_CONSUMERS,
            *contract.EXTERNAL_REFERENCE_EVENT_CONSUMERS,
            *contract.RECOMMENDABLE_CONSUMERS,
        ],
        "users": contract.build_users_child_consumers(list(contract.USERS_CHILD_SUBJECTS)),
        "orders": _orders_consumers(),
        "taxonomy": contract.TAXONOMY_CATEGORY_CONSUMERS,
    }
    started: list[tuple[str, UnifiedMessageBroker]] = []
    try:
        for label in CONSUMER_BROKER_LABELS:
            broker = _consumer_broker(consumer_sets[label], partial(heartbeat.tick, label))
            await broker.start()
            started.append((label, broker))
    except BaseException:
        for label, broker in reversed(started):
            await _bounded(f"{label} consumer broker", broker.stop())
        raise
    _consumer_brokers = started
    logger.info("Consumers started: %s", "+".join(CONSUMER_BROKER_LABELS))


async def stop_consumers() -> None:
    global _consumer_brokers

    brokers, _consumer_brokers = _consumer_brokers, []
    for label, broker in reversed(brokers):
        await _bounded(f"{label} consumer broker", broker.stop())
    logger.info("Consumers stopped")
