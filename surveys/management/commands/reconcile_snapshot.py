"""Publish a current-state snapshot of assessments and collections.

For every existing Survey and SurveyCollection, write one ``Created``
event (and a ``Published`` event when its status is published) to the
outbox. The in-process relay forwards the rows to NATS.

Use this once after seeding via fixtures, or to re-broadcast state to
a new downstream consumer. Receivers must be idempotent on ``event_id``.
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand, CommandError

from app.messaging import publish
from survey_collections.events import CollectionCreated, CollectionPublished
from survey_collections.messaging import serialize_collection
from survey_collections.models import SurveyCollection
from surveys.events import SurveyCreated, SurveyPublished
from surveys.messaging import serialize_survey
from surveys.models import Survey

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Publish Created/Published events for every Survey and SurveyCollection "
        "to the outbox; the in-process relay forwards them to NATS."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--published-only", action="store_true")
        parser.add_argument("--surveys-only", action="store_true")
        parser.add_argument("--collections-only", action="store_true")

    def handle(self, **options):
        if options["surveys_only"] and options["collections_only"]:
            raise CommandError("Pass at most one of --surveys-only / --collections-only")

        do_surveys = not options["collections_only"]
        do_collections = not options["surveys_only"]
        dry_run = options["dry_run"]
        published_only = options["published_only"]

        if do_surveys:
            emitted, skipped = self._publish_surveys(
                published_only=published_only, dry_run=dry_run
            )
            verb = "would emit" if dry_run else "emitted"
            self.stdout.write(
                self.style.SUCCESS(f"[surveys] {verb}={emitted} skipped={skipped}")
            )
        if do_collections:
            emitted, skipped = self._publish_collections(
                published_only=published_only, dry_run=dry_run
            )
            verb = "would emit" if dry_run else "emitted"
            self.stdout.write(
                self.style.SUCCESS(f"[collections] {verb}={emitted} skipped={skipped}")
            )

    def _publish_surveys(self, *, published_only: bool, dry_run: bool) -> tuple[int, int]:
        qs = Survey.objects.all().order_by("pk")
        if published_only:
            qs = qs.filter(status=Survey.STATUS_PUBLISHED)

        emitted = skipped = 0
        for survey in qs.iterator():
            payload = serialize_survey(survey)
            if not payload["organization_id"]:
                skipped += 1
                logger.warning(
                    "[surveys] skip id=%s reason=missing_organization_id", survey.pk
                )
                continue
            if not dry_run:
                publish(SurveyCreated(
                    aggregate_id=survey.pk,
                    organization_id=payload["organization_id"],
                    survey=payload,
                ))
            emitted += 1
            if survey.status == Survey.STATUS_PUBLISHED:
                if not dry_run:
                    publish(SurveyPublished(
                        aggregate_id=survey.pk,
                        organization_id=payload["organization_id"],
                        survey=payload,
                    ))
                emitted += 1
        return emitted, skipped

    def _publish_collections(self, *, published_only: bool, dry_run: bool) -> tuple[int, int]:
        qs = SurveyCollection.objects.all().order_by("pk")
        if published_only:
            qs = qs.filter(status=SurveyCollection.STATUS_PUBLISHED)

        emitted = skipped = 0
        for collection in qs.iterator():
            payload = serialize_collection(collection)
            if not payload["organization_id"]:
                skipped += 1
                logger.warning(
                    "[collections] skip id=%s reason=missing_organization_id",
                    collection.pk,
                )
                continue
            if not dry_run:
                publish(CollectionCreated(
                    aggregate_id=collection.pk,
                    organization_id=payload["organization_id"],
                    collection=payload,
                ))
            emitted += 1
            if collection.status == SurveyCollection.STATUS_PUBLISHED:
                if not dry_run:
                    publish(CollectionPublished(
                        aggregate_id=collection.pk,
                        organization_id=payload["organization_id"],
                        collection=payload,
                    ))
                emitted += 1
        return emitted, skipped
