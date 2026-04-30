from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from survey_collections.models import SurveyCollection
from surveys.models import Survey

from pricing.models import Price


class Command(BaseCommand):
    help = (
        "Create amount_cents=0 Price rows for every currency in "
        "AVAILABLE_CURRENCIES that an existing Survey or SurveyCollection "
        "does not yet have."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--currencies",
            help="Override AVAILABLE_CURRENCIES (CSV, e.g. EGP,USD).",
        )
        parser.add_argument(
            "--surveys-only",
            action="store_true",
            help="Backfill Surveys only.",
        )
        parser.add_argument(
            "--collections-only",
            action="store_true",
            help="Backfill SurveyCollections only.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created without writing.",
        )

    def handle(self, *args, **opts):
        if opts["currencies"]:
            currencies = [c.strip() for c in opts["currencies"].split(",") if c.strip()]
        else:
            currencies = list(getattr(settings, "AVAILABLE_CURRENCIES", []) or [])

        if not currencies:
            self.stdout.write(self.style.WARNING("No currencies configured; nothing to do."))
            return

        do_surveys = not opts["collections_only"]
        do_collections = not opts["surveys_only"]
        dry = opts["dry_run"]

        created_total = 0

        with transaction.atomic():
            if do_surveys:
                created_total += self._backfill(
                    Survey.objects.all(),
                    parent_field="survey",
                    currencies=currencies,
                    dry=dry,
                )
            if do_collections:
                created_total += self._backfill(
                    SurveyCollection.objects.all(),
                    parent_field="collection",
                    currencies=currencies,
                    dry=dry,
                )

            if dry:
                transaction.set_rollback(True)

        prefix = "[dry-run] would create" if dry else "Created"
        self.stdout.write(self.style.SUCCESS(f"{prefix} {created_total} Price row(s)."))

    def _backfill(self, queryset, *, parent_field: str, currencies, dry: bool) -> int:
        parent_ids = list(queryset.values_list("id", flat=True))
        if not parent_ids:
            return 0

        existing = set(
            Price.objects.filter(**{f"{parent_field}_id__in": parent_ids})
            .values_list(f"{parent_field}_id", "currency")
        )

        to_create = []
        for parent_id in parent_ids:
            for currency in currencies:
                if (parent_id, currency) in existing:
                    continue
                to_create.append(
                    Price(**{
                        f"{parent_field}_id": parent_id,
                        "currency": currency,
                        "amount_cents": 0,
                    })
                )

        if to_create and not dry:
            Price.objects.bulk_create(to_create, batch_size=1000)

        self.stdout.write(
            f"  {parent_field}: {len(parent_ids)} parents, "
            f"{len(to_create)} missing price row(s)."
        )
        return len(to_create)
