from __future__ import annotations

from typing import Optional

from unimessaging.broker.broker import UnifiedMessageBroker
from unimessaging.broker.client import UnifiedMessaging
from unimessaging.broker.config import JetStreamConsumer
from unimessaging.broker.registry import HandlerRegistry
from unimessaging.integrations.django import (
    get_broker,
    start_messaging as _start_messaging,
    stop_messaging as _stop_messaging,
)


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
    return await _start_messaging(
        subjects=subjects,
        service_name=service_name,
        url=url,
        enable_durable=enable_durable,
        stream_name=stream_name,
        stream_subjects=stream_subjects,
        consumers=consumers,
        pull_batch=pull_batch,
        pull_timeout=pull_timeout,
        registry=registry,
    )


def get_messaging() -> Optional[UnifiedMessaging]:
    broker = get_broker()
    return getattr(broker, "client", None) if broker is not None else None


async def stop_messaging() -> None:
    await _stop_messaging()
