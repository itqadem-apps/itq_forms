from __future__ import annotations

import asyncio
import signal

from django.conf import settings
from django.core.management.base import BaseCommand

from app.messaging import start_messaging, stop_messaging
from recommendations.consumer import handle_recommendable_event
from unimessaging.broker.registry import HandlerRegistry


def _to_handler_pattern(subject: str) -> str:
    """Convert NATS wildcards to fnmatch wildcards used by unimessaging registry."""
    return subject.replace(">", "*")


class Command(BaseCommand):
    help = "Consume NATS events and upsert Recommendable catalog rows"

    def add_arguments(self, parser):
        parser.add_argument(
            "--subjects",
            default=",".join(settings.MESSAGE_BROKER_SUBJECTS),
            help="Comma-separated subjects to subscribe to",
        )

    async def _run(self, subjects: list[str], stop_flag: dict[str, bool]) -> None:
        registry = HandlerRegistry()
        for subject in subjects:
            registry.register_handler(_to_handler_pattern(subject), handle_recommendable_event)

        await start_messaging(
            subjects=subjects,
            service_name=settings.SERVICE_NAME,
            url=settings.NATS_URL,
            enable_durable=settings.JETSTREAM_ENABLED,
            registry=registry,
        )

        self.stdout.write(self.style.SUCCESS(f"Recommendable consumer started (subjects={subjects})"))

        try:
            while not stop_flag["stop"]:
                await asyncio.sleep(0.5)
        finally:
            await stop_messaging()
            self.stdout.write(self.style.SUCCESS("Recommendable consumer stopped"))

    def handle(self, **options):
        raw_subjects = options["subjects"] or ""
        subjects = [s.strip() for s in raw_subjects.split(",") if s.strip()]
        if not subjects:
            self.stderr.write(self.style.ERROR("No subjects configured for recommendable consumer"))
            return

        stop_flag = {"stop": False}

        def _stop(sig, frame):
            stop_flag["stop"] = True

        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)

        asyncio.run(self._run(subjects, stop_flag))
