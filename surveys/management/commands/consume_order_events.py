from __future__ import annotations

import asyncio
import json
import signal

from django.conf import settings
from django.core.management.base import BaseCommand
from nats.errors import TimeoutError as NATSTimeout
from pydantic import BaseModel, ConfigDict, Field
from unimessaging.broker.client import UnifiedMessaging
from unimessaging.broker.config import MessagingConfig

from app import messaging_contract as contract
from surveys.order_messaging import handle_order_event


class OrderEventHeadersModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event_type: str | None = None


class OrderEventMetaModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    subject: str = ""
    headers: OrderEventHeadersModel = Field(default_factory=OrderEventHeadersModel)
    metadata: dict[str, object] | None = Field(default_factory=dict)


def _messaging_config() -> MessagingConfig:
    return MessagingConfig(
        backend="nats",
        url=settings.NATS_URL,
        name=settings.SERVICE_NAME,
        enable_durable=settings.JETSTREAM_ENABLED,
        stream_name=contract.ORDERS_STREAM_NAME,
        stream_subjects=contract.ORDERS_STREAM_SUBJECTS,
        default_headers={"service": settings.SERVICE_NAME},
    )


class Command(BaseCommand):
    help = "Consume order payment/refund events and maintain local forms usage records"

    def add_arguments(self, parser):
        parser.add_argument(
            "--subjects",
            default=",".join(contract.ORDERS_EVENT_SUBJECTS),
            help="Comma-separated order event subjects to subscribe to",
        )

    async def _handle_message(self, data: bytes, meta: dict) -> None:
        subject = meta.get("subject", "")
        try:
            payload = json.loads(data.decode()) if data else {}
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Invalid JSON on {subject}: {exc}"))
            return

        normalized_meta = OrderEventMetaModel.model_validate(meta).model_dump(exclude_none=True)
        await handle_order_event(payload, normalized_meta)

    async def _pull_loop(
        self,
        messaging: UnifiedMessaging,
        *,
        subject: str,
        durable: str,
        stop_flag: dict[str, bool],
    ) -> None:
        sub = await messaging.adapter.js.pull_subscribe(subject, durable=durable)
        while not stop_flag["stop"]:
            try:
                msgs = await sub.fetch(
                    settings.JETSTREAM_PULL_BATCH,
                    timeout=settings.JETSTREAM_PULL_TIMEOUT,
                )
            except NATSTimeout:
                msgs = []
            for msg in msgs:
                meta = {"subject": msg.subject, "headers": dict(msg.headers or {})}
                try:
                    await self._handle_message(msg.data, meta)
                    await msg.ack()
                except Exception:
                    await msg.nak()
                    raise

    async def _run(self, subjects: list[str], stop_flag: dict[str, bool]) -> None:
        messaging = UnifiedMessaging(_messaging_config())
        await messaging.start()

        tasks: list[asyncio.Task] = []
        if settings.JETSTREAM_ENABLED:
            for subject in subjects:
                tasks.append(
                    asyncio.create_task(
                        self._pull_loop(
                            messaging,
                            subject=subject,
                            durable=contract.order_durable_name(subject, subjects),
                            stop_flag=stop_flag,
                        )
                    )
                )
        else:
            for subject in subjects:
                await messaging.subscribe(subject, self._handle_message)

        self.stdout.write(self.style.SUCCESS(f"Order consumer started (subjects={subjects})"))

        try:
            while not stop_flag["stop"]:
                await asyncio.sleep(0.5)
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await messaging.stop()
            self.stdout.write(self.style.SUCCESS("Order consumer stopped"))

    def handle(self, **options):
        subjects = [s.strip() for s in str(options["subjects"] or "").split(",") if s.strip()]
        if not subjects:
            self.stderr.write(self.style.ERROR("No subjects configured for order consumer"))
            return

        stop_flag = {"stop": False}

        def _stop(sig, frame):
            stop_flag["stop"] = True

        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)
        asyncio.run(self._run(subjects, stop_flag))
