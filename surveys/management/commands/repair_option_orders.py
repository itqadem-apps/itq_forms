"""Report answer-option order sequences that are not a clean 1..N.

Asked for after a respondent found a four-point Likert question rendering three
choices: the schema held orders 1, 2, 4 and the client, correctly, drew what it
was given. Sections and questions resequence themselves after a delete;
options did not, so a hole there was permanent. That is fixed in
``surveys.models.signals``, but the fix only holds from now on — every schema
already carrying a hole still carries it, and this command finds them.
It is the sibling of ``repair_snapshot_sections`` and behaves the same way:
it reports by default and writes only under ``--apply``.

Two shapes, and they mean different things:

* **gap** — an order is missing. An option was deleted; the surviving choices
  are intact but the instrument is short one. Resequencing makes the sequence
  clean again; it cannot bring the choice back. Only an author or a backup can.
* **duplicate** — two options share an order. ``AnswerSchemaOption.save``
  assigns ``count() + 1``, so an option added to a schema that already had a
  gap was handed an order already in use. Both choices are present and
  ``Meta.ordering`` breaks the tie arbitrarily, which means the two can swap
  places between requests.

Only a gap loses data. A duplicate is purely an ordering defect and
``--apply`` fully repairs it.

Dry-run by default; pass ``--apply`` to resequence. ``--apply`` never deletes
and never invents an option — it renumbers what is there.
"""

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from surveys.models import AnswerSchemaOption


class Command(BaseCommand):
    help = "Find answer schemas whose option order has a hole, and close it."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Resequence the reported schemas. Without it the command only reports.",
        )
        parser.add_argument(
            "--survey",
            type=int,
            action="append",
            dest="surveys",
            help="Limit to one survey. Repeatable.",
        )

    def handle(self, *args, **options):
        qs = AnswerSchemaOption.objects.all()
        if options.get("surveys"):
            qs = qs.filter(survey_id__in=options["surveys"])

        by_schema = defaultdict(list)
        for row in qs.values("id", "schema_id", "survey_id", "question_id", "order").order_by("order", "id"):
            by_schema[row["schema_id"]].append(row)

        gaps, duplicates = [], []
        for schema_id, rows in by_schema.items():
            orders = [r["order"] for r in rows]
            if orders == list(range(1, len(orders) + 1)):
                continue
            (duplicates if len(set(orders)) != len(orders) else gaps).append((schema_id, rows))

        for label, found in (("gap", gaps), ("duplicate", duplicates)):
            for schema_id, rows in found:
                orders = [r["order"] for r in rows]
                missing = sorted(set(range(1, max(orders) + 1)) - set(orders))
                self.stdout.write(
                    f"{label:9} schema={schema_id} survey={rows[0]['survey_id']} "
                    f"question={rows[0]['question_id']} orders={orders}"
                    + (f" missing={missing}" if missing else "")
                )

        total = len(gaps) + len(duplicates)
        self.stdout.write(
            self.style.SUCCESS(f"{len(by_schema)} schemas checked, {total} not contiguous "
                               f"({len(gaps)} gap, {len(duplicates)} duplicate)")
        )

        if not total or not options["apply"]:
            if total:
                self.stdout.write("Dry run. Pass --apply to resequence.")
            return

        with transaction.atomic():
            written = 0
            for _, rows in gaps + duplicates:
                for idx, row in enumerate(rows, start=1):
                    if row["order"] != idx:
                        AnswerSchemaOption.objects.filter(pk=row["id"]).update(order=idx)
                        written += 1
        self.stdout.write(self.style.SUCCESS(f"Resequenced {written} options."))
