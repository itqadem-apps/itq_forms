from django.core.management.base import BaseCommand
from django.db import transaction

from surveys.factories import SurveyFactory
from surveys.models import Survey


class Command(BaseCommand):
    help = "Seed Survey records using a factory"

    def add_arguments(self, parser):
        parser.epilog = (
            "Examples:\n"
            "  python manage.py seed_surveys --count 50\n"
            "  python manage.py seed_surveys --truncate --count 10 --status published\n"
        )
        parser.add_argument("--count", type=int, default=25, help="Number of surveys to create")
        parser.add_argument(
            "--truncate",
            action="store_true",
            help="Delete existing surveys before creating new ones",
        )
        parser.add_argument(
            "--status",
            type=str,
            default=None,
            help="Force status (draft|pending|published|suspended)",
        )
        parser.add_argument(
            "--assignable",
            action="store_true",
            help="Force assignable_to_user=True",
        )
        parser.add_argument(
            "--timed",
            action="store_true",
            help="Force is_timed=True",
        )

    def handle(self, *args, **options):
        count = options["count"]
        if count <= 0:
            self.stdout.write(self.style.WARNING("Nothing to do: --count must be > 0"))
            return

        overrides = {}
        if options["status"]:
            overrides["status"] = options["status"]
        if options["assignable"]:
            overrides["assignable_to_user"] = True
        if options["timed"]:
            overrides["is_timed"] = True

        with transaction.atomic():
            deleted = 0
            if options["truncate"]:
                deleted, _ = Survey.objects.all().delete()

            created = SurveyFactory.create_batch(count, **overrides)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded surveys: created={len(created)} deleted={deleted} (overrides={overrides or 'none'})"
            )
        )
