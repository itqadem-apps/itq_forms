"""Report rows that carry no owning organization. Reads only; writes nothing.

`SPEC-forms-permission-gates` CAP-2 shipped `ensure_in_org`, which refuses a row
whose `organization_id` does not match the caller's — and a null owner matches
nobody, so every such row is now invisible to every tenant caller. The story's
third step asked for the size of that exposure to be established *before*
shipping, and it never was. A migration that tried to repair the rows instead
(0040) was reverted as indiscriminate: `Survey` carries no creator column, so
attributing the rows is a guess, and guessing wrong hands one tenant another
tenant's data permanently.

So this command only counts. Deciding what the rows are and who they belong to
is a judgement for a human with product context, and nothing here pre-empts it.

Where the nulls come from, from the history:

* 2026-04-15 (`6aacd92`) added `Survey.organization_id`, nullable.
* 2026-04-26 (`0035_backfill_organization_id`) set every row then existing to
  the `itqadem` organization. After it ran, no row was null.
* 2026-09-22 (`7febec3`, CAP-1) made `create_survey` bind the owner from the
  caller's auth context. Before that the GraphQL write path never set the
  column and the frontend never sent it, so **every row created through the API
  in those five months is null-owned**.

That window is the one to expect rows in. Anything outside it wants explaining
before it is repaired — in particular the legacy loader sets the column
explicitly (`legacy_load.py:819`), so its rows should not appear here.

A null owner is not only a read problem. `messaging.build_survey_payload_or_log`
skips publishing any survey with no organization, logging
``reason=missing_organization_id``, so these rows have never emitted a domain
event to any consumer. Those log lines are an independent way to size the same
population if this command cannot be run where the data lives.

`accounts.ChildGuardian` is reported separately and must not be repaired in the
same breath as the other two: it is a read-only NATS projection of `itq_users`
(so the next `GuardianRelation` event overwrites whatever is written here), and
it is the supervision source `user_surveys.child_projection` reads to scope
`submissions:read`. Attributing a guardian row grants that organization's
`submissions:read` holders supervision over that child's whole submission
history — the outcome the CAP-2 story explicitly forbids.
"""


from django.core.management.base import BaseCommand
from django.db.models import Count
from django.db.models.functions import TruncMonth

from accounts.models import ChildGuardian
from survey_collections.models import SurveyCollection
from surveys.models import Survey

#: The window in which the API could create a null-owned row: from the 0035
#: backfill to the CAP-1 write binding. Rows outside it are the interesting ones.
GAP_OPENED = "2026-04-26"
GAP_CLOSED = "2026-09-22"


class Command(BaseCommand):
    help = "Count rows with no organization_id. Reports only; writes nothing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--by-month",
            action="store_true",
            help="Break the null-owned surveys and collections down by creation month.",
        )

    def handle(self, *args, **options):
        self.stdout.write(f"Ownership gap window: {GAP_OPENED} .. {GAP_CLOSED}\n")

        surveys = Survey.objects.filter(organization_id__isnull=True)
        collections = SurveyCollection.objects.filter(organization_id__isnull=True)

        for label, qs, total_qs in (
            ("surveys_survey", surveys, Survey.objects.all()),
            ("survey_collections_surveycollection", collections, SurveyCollection.objects.all()),
        ):
            total = total_qs.count()
            null = qs.count()
            live = qs.filter(deleted_at__isnull=True).count()
            share = f"{(null / total * 100):.1f}%" if total else "n/a"
            self.stdout.write(
                f"{label:40} {null:>7} null of {total:>7} ({share})"
                f"  — {live} not soft-deleted"
            )

        # Reported apart, and deliberately not summed with the rows above: this
        # table is a projection that rewrites itself, and repairing it changes
        # who can read a child's submissions. See the module docstring.
        guardians = ChildGuardian.objects.filter(organization_id__isnull=True)
        self.stdout.write(
            f"{'accounts_childguardian':40} {guardians.count():>7} null of "
            f"{ChildGuardian.objects.count():>7}  — projection, do not repair here"
        )

        if surveys.exists():
            self.stdout.write("\nNull-owned surveys by type and status:")
            for row in (
                surveys.values("survey_type", "status")
                .annotate(n=Count("id"))
                .order_by("-n")
            ):
                self.stdout.write(
                    f"  {row['survey_type'] or '(none)':<12} {row['status'] or '(none)':<12} {row['n']:>7}"
                )

            first = surveys.order_by("created_at").values_list("created_at", flat=True).first()
            last = surveys.order_by("-created_at").values_list("created_at", flat=True).first()
            self.stdout.write(f"\n  created between {first} and {last}")
            outside = surveys.exclude(
                created_at__date__gte=GAP_OPENED, created_at__date__lte=GAP_CLOSED
            ).count()
            if outside:
                self.stdout.write(
                    self.style.WARNING(
                        f"  {outside} of them fall OUTSIDE the gap window — a second "
                        f"source of nulls the history above does not explain."
                    )
                )

        if options["by_month"]:
            for label, qs in (("survey", surveys), ("collection", collections)):
                if not qs.exists():
                    continue
                self.stdout.write(f"\nNull-owned {label}s by month:")
                for row in (
                    qs.annotate(month=TruncMonth("created_at"))
                    .values("month")
                    .annotate(n=Count("id"))
                    .order_by("month")
                ):
                    month = row["month"].date().isoformat() if row["month"] else "(no date)"
                    self.stdout.write(f"  {month}  {row['n']:>7}")

        self.stdout.write(
            self.style.SUCCESS(
                "\nRead-only: nothing was written. Attributing these rows needs a "
                "per-row signal this database does not carry — see the module docstring."
            )
        )
