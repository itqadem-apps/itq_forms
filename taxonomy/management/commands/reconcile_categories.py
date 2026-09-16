"""CAP-2 reconcile: repoint forms' legacy categories onto their taxonomy counterparts.

Forms minted its seven categories locally with uuid4 ids that taxonomy has never
heard of (taxonomy/migrations/0003_backfill_path_text_and_english.py). The
survey tree was minted in taxonomy carrying the same seven terms, deliberately
reusing the legacy wording and slugs so this match is exact rather than
approximate -- notably `interventions-therapeutic-programs`, which is NOT the
wording the Main tree uses.

Matching is by translation slug first, then by translation name, both
case-insensitively. A legacy row that matches nothing is reported and left
exactly as it is: an unmatched category is a ruling for a person, and the one
thing this command must never do is drop a row whose SET_NULL foreign keys would
silently strip the category off live surveys and collections.

Run after `seed_categories` (or after the projection has caught up), and only
once -- a reconciled legacy row is deleted, so a second run finds nothing to do.
"""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from survey_collections.models import SurveyCollection
from surveys.models import Survey
from taxonomy.models import Category, CategoryTranslation


def _keys(category: Category) -> set[str]:
    """Every string this category could be matched on, normalised."""
    keys = set()
    for translation in category.translations.all():
        for value in (translation.slug, translation.name):
            if value:
                keys.add(value.strip().casefold())
    if category.name:
        keys.add(category.name.strip().casefold())
    if category.path_text:
        keys.add(category.path_text.strip().casefold())
    return keys


class Command(BaseCommand):
    help = "Repoint legacy forms categories onto their counterparts in the configured tree."

    def add_arguments(self, parser):
        parser.add_argument("--tree-id", default=None, help="Defaults to settings.CATEGORY_TREE_ID.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report the matches and the repointing without writing anything.",
        )

    def handle(self, *args, **options):
        tree_id_raw = options["tree_id"] or settings.CATEGORY_TREE_ID
        if not tree_id_raw:
            raise CommandError("No tree: set CATEGORY_TREE_ID or pass --tree-id.")
        try:
            tree_id = UUID(str(tree_id_raw))
        except (TypeError, ValueError):
            raise CommandError(f"Not a UUID: {tree_id_raw!r}")

        target = list(Category.live(tree_id=tree_id).prefetch_related("translations"))
        if not target:
            raise CommandError(
                f"Tree {tree_id} holds no categories here. Run seed_categories first, "
                "or wait for the projection to catch up."
            )

        legacy = list(
            Category.objects.exclude(tree_id=tree_id)
            .filter(deleted_at__isnull=True)
            .prefetch_related("translations")
        )
        if not legacy:
            self.stdout.write(self.style.SUCCESS("No legacy categories left; nothing to do."))
            return

        # Build the lookup, and refuse to guess when two target categories answer
        # to the same key -- an ambiguous match is a ruling, not a coin flip.
        by_key: dict[str, list[Category]] = defaultdict(list)
        for category in target:
            for key in _keys(category):
                by_key[key].append(category)

        matched: list[tuple[Category, Category]] = []
        unmatched: list[Category] = []
        ambiguous: list[tuple[Category, list[Category]]] = []

        for row in legacy:
            candidates: list[Category] = []
            for key in _keys(row):
                for candidate in by_key.get(key, []):
                    if candidate not in candidates:
                        candidates.append(candidate)
            if not candidates:
                unmatched.append(row)
            elif len(candidates) > 1:
                ambiguous.append((row, candidates))
            else:
                matched.append((row, candidates[0]))

        for row, target_row in matched:
            self.stdout.write(f"  match  {row.name!r}  {row.category_id} -> {target_row.category_id}")
        for row, candidates in ambiguous:
            names = ", ".join(str(c.category_id) for c in candidates)
            self.stdout.write(
                self.style.WARNING(f"  AMBIGUOUS  {row.name!r} {row.category_id} -> [{names}]")
            )
        for row in unmatched:
            self.stdout.write(self.style.WARNING(f"  UNMATCHED  {row.name!r} {row.category_id}"))

        if options["dry_run"]:
            self.stdout.write(
                f"Dry run: {len(matched)} matched, {len(ambiguous)} ambiguous, "
                f"{len(unmatched)} unmatched. Nothing written."
            )
            return

        surveys_moved = 0
        collections_moved = 0
        with transaction.atomic():
            for row, target_row in matched:
                surveys_moved += Survey.objects.filter(category_id=row.category_id).update(
                    category_id=target_row.category_id
                )
                collections_moved += SurveyCollection.objects.filter(
                    category_id=row.category_id
                ).update(category_id=target_row.category_id)

                # Only now is the legacy row unreferenced. Deleting it earlier
                # would let SET_NULL strip the category off live rows.
                CategoryTranslation.objects.filter(category_id=row.category_id).delete()
                Category.objects.filter(category_id=row.category_id).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Repointed {surveys_moved} survey(s) and {collections_moved} collection(s) "
                f"across {len(matched)} category(ies); retired {len(matched)} legacy row(s)."
            )
        )
        if ambiguous or unmatched:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(ambiguous)} ambiguous and {len(unmatched)} unmatched category(ies) "
                    "were left untouched, with their surveys and collections still pointing at "
                    "them. Each needs a human ruling before it can be retired."
                )
            )
