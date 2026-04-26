from __future__ import annotations

import asyncio
import re
import signal

from django.conf import settings
from django.core.management.base import BaseCommand

from accounts.messaging import handle_child_event, handle_child_guardian_event
from app.messaging import start_messaging, stop_messaging
from unimessaging.broker.config import JetStreamConsumer
from unimessaging.broker.registry import HandlerRegistry


def _to_handler_pattern(subject: str) -> str:
    return subject.replace(">", "*")


def _build_jetstream_consumers(subjects: list[str]) -> list[JetStreamConsumer]:
    return [
        JetStreamConsumer(
            label="users",
            subject=subject,
            durable=f"forms-{re.sub(r'[^a-zA-Z0-9_-]+', '-', subject).strip('-')}-consumer",
        )
        for subject in subjects
    ]


class Command(BaseCommand):
    help = "Consume users child/guardian events and maintain local forms child projections"

    def add_arguments(self, parser):
        parser.add_argument(
            "--subjects",
            default=",".join(settings.USERS_CHILD_EVENT_SUBJECTS),
            help="Comma-separated users child event subjects to subscribe to",
        )

    async def _run(self, subjects: list[str], stop_flag: dict[str, bool]) -> None:
        registry = HandlerRegistry()
        for subject in subjects:
            pattern = _to_handler_pattern(subject)
            if subject.startswith("users.child_guardian."):
                registry.register_handler(pattern, handle_child_guardian_event)
            else:
                registry.register_handler(pattern, handle_child_event)

        await start_messaging(
            subjects=subjects,
            service_name=settings.SERVICE_NAME,
            url=settings.NATS_URL,
            enable_durable=settings.JETSTREAM_ENABLED,
            stream_name=settings.USERS_CHILD_EVENT_STREAM_NAME or None,
            stream_subjects=settings.USERS_CHILD_EVENT_STREAM_SUBJECTS or None,
            consumers=_build_jetstream_consumers(subjects),
            pull_batch=settings.JETSTREAM_PULL_BATCH,
            pull_timeout=settings.JETSTREAM_PULL_TIMEOUT,
            registry=registry,
        )

        self.stdout.write(self.style.SUCCESS(f"User child consumer started (subjects={subjects})"))

        try:
            while not stop_flag["stop"]:
                await asyncio.sleep(0.5)
        finally:
            await stop_messaging()
            self.stdout.write(self.style.SUCCESS("User child consumer stopped"))

    def handle(self, **options):
        subjects = [s.strip() for s in str(options["subjects"] or "").split(",") if s.strip()]
        if not subjects:
            self.stderr.write(self.style.ERROR("No subjects configured for user child consumer"))
            return

        stop_flag = {"stop": False}

        def _stop(sig, frame):
            stop_flag["stop"] = True

        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)
        asyncio.run(self._run(subjects, stop_flag))
