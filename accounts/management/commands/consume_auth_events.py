from __future__ import annotations

import asyncio
import signal

from django.conf import settings
from django.core.management.base import BaseCommand

from app import messaging_contract as contract
from accounts.messaging import handle_auth_user_registered
from app.messaging import start_messaging, stop_messaging
from unimessaging.broker.registry import HandlerRegistry


class Command(BaseCommand):
    help = "Consume auth.UserRegistered events and upsert local forms users"

    async def _run(self, stop_flag: dict[str, bool]) -> None:
        registry = HandlerRegistry()
        registry.register_handler("auth.UserRegistered", handle_auth_user_registered)

        await start_messaging(
            subjects=["__forms_auth_internal.none"],
            service_name=settings.SERVICE_NAME,
            url=settings.NATS_URL,
            enable_durable=settings.JETSTREAM_ENABLED,
            stream_name=contract.FORMS_STREAM_NAME,
            stream_subjects=contract.FORMS_STREAM_SUBJECTS,
            consumers=list(contract.AUTH_CONSUMERS),
            pull_batch=settings.JETSTREAM_PULL_BATCH,
            pull_timeout=settings.JETSTREAM_PULL_TIMEOUT,
            registry=registry,
        )

        self.stdout.write(self.style.SUCCESS("Auth consumer started (subject=auth.UserRegistered)"))

        try:
            while not stop_flag["stop"]:
                await asyncio.sleep(0.5)
        finally:
            await stop_messaging()
            self.stdout.write(self.style.SUCCESS("Auth consumer stopped"))

    def handle(self, **options):
        stop_flag = {"stop": False}

        def _stop(sig, frame):
            stop_flag["stop"] = True

        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)
        asyncio.run(self._run(stop_flag))
