from __future__ import annotations

import asyncio
import signal

from django.conf import settings
from django.core.management.base import BaseCommand

from app import messaging_contract as contract
from app.messaging import start_messaging, stop_messaging
from curriculum_references.consumer import (
    handle_curriculum_enrollment_event,
    handle_curriculum_reference_event,
)
from unimessaging.broker.registry import HandlerRegistry


def _to_handler_pattern(subject: str) -> str:
    return subject.replace(">", "*")


class Command(BaseCommand):
    help = "Consume curriculum reference and enrollment events"

    def add_arguments(self, parser):
        parser.add_argument(
            "--subjects",
            default=",".join(contract.CURRICULUM_EVENT_SUBJECTS),
            help="Comma-separated curriculum subjects to subscribe to",
        )

    async def _run(self, subjects: list[str], stop_flag: dict[str, bool]) -> None:
        registry = HandlerRegistry()
        for subject in subjects:
            pattern = _to_handler_pattern(subject)
            if subject.endswith(".curriculum_enrollment"):
                registry.register_handler(pattern, handle_curriculum_enrollment_event)
            else:
                registry.register_handler(pattern, handle_curriculum_reference_event)

        await start_messaging(
            subjects=subjects,
            service_name=settings.SERVICE_NAME,
            url=settings.NATS_URL,
            enable_durable=settings.JETSTREAM_ENABLED,
            stream_name=contract.FORMS_STREAM_NAME,
            stream_subjects=contract.FORMS_STREAM_SUBJECTS,
            consumers=contract.CURRICULUM_EVENT_CONSUMERS,
            pull_batch=settings.JETSTREAM_PULL_BATCH,
            pull_timeout=settings.JETSTREAM_PULL_TIMEOUT,
            registry=registry,
        )

        self.stdout.write(self.style.SUCCESS(f"Curriculum consumer started (subjects={subjects})"))

        try:
            while not stop_flag["stop"]:
                await asyncio.sleep(0.5)
        finally:
            await stop_messaging()
            self.stdout.write(self.style.SUCCESS("Curriculum consumer stopped"))

    def handle(self, **options):
        subjects = [s.strip() for s in str(options["subjects"] or "").split(",") if s.strip()]
        if not subjects:
            self.stderr.write(self.style.ERROR("No subjects configured for curriculum consumer"))
            return

        stop_flag = {"stop": False}

        def _stop(sig, frame):
            stop_flag["stop"] = True

        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)
        asyncio.run(self._run(subjects, stop_flag))
