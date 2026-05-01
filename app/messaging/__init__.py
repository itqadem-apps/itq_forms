from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Optional

from unimessaging.broker.broker import UnifiedMessageBroker
from unimessaging.broker.client import UnifiedMessaging
from unimessaging.broker.registry import HandlerRegistry
from unimessaging.integrations.django import (
    get_broker,
    start_messaging as _start_messaging,
    stop_messaging as _stop_messaging,
)

try:
    from unimessaging.broker.config import JetStreamConsumer
except ImportError:
    @dataclass(frozen=True)
    class JetStreamConsumer:
        label: str
        subject: str
        durable: str


async def start_messaging(
    *,
    subjects: list[str],
    service_name: str,
    url: str = "nats://localhost:4222",
    enable_durable: bool = False,
    stream_name: str | None = None,
    stream_subjects: list[str] | None = None,
    consumers: list[JetStreamConsumer] | None = None,
    pull_batch: int = 10,
    pull_timeout: float = 1.0,
    registry: Optional[HandlerRegistry] = None,
) -> UnifiedMessageBroker:
    kwargs = {
        "subjects": subjects,
        "service_name": service_name,
        "url": url,
        "enable_durable": enable_durable,
        "stream_name": stream_name,
        "stream_subjects": stream_subjects,
        "consumers": consumers,
        "pull_batch": pull_batch,
        "pull_timeout": pull_timeout,
        "registry": registry,
    }
    supported_args = inspect.signature(_start_messaging).parameters
    return await _start_messaging(
        **{key: value for key, value in kwargs.items() if key in supported_args}
    )


def get_messaging() -> Optional[UnifiedMessaging]:
    broker = get_broker()
    return getattr(broker, "client", None) if broker is not None else None


async def stop_messaging() -> None:
    await _stop_messaging()


from app.messaging.publisher import publish  # noqa: E402

__all__ = [
    "JetStreamConsumer",
    "get_messaging",
    "publish",
    "start_messaging",
    "stop_messaging",
]
