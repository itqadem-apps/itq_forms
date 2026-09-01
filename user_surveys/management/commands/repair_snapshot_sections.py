"""Report — and optionally repair — snapshot questions with no section link.

``userSurvey.sections[].questions`` is the reverse of ``UserQuestion.section``.
A snapshot question whose ``section`` is NULL therefore vanishes from every
section while still appearing in the flat ``userSurvey.questions`` list, which
is what a results screen sees as a section with zero questions.

Two shapes produce that, and they need different answers:

* **recoverable** — the source question has a section, but the snapshot lost
  the link. ``origin_id`` still records which source rows these were, so the
  link can be rebuilt exactly.
* **unsectioned at source** — the source question itself has no section
  (``Question.section`` is nullable). There is nothing to rebuild; the question
  legitimately belongs to no section and only the flat list can show it.

Dry-run by default; pass ``--apply`` to write.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from surveys.models import Question
from user_surveys.models import UserQuestion, UserSection


class Command(BaseCommand):
    help = "Find snapshot questions with no section, and relink the recoverable ones."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the repairs. Without it the command only reports.",
        )
        parser.add_argument(
            "--user-survey",
            type=int,
            action="append",
            dest="user_surveys",
            help="Limit to these attempt ids. Repeatable.",
        )

    def handle(self, *args, **options):
        orphans = UserQuestion.objects.filter(section__isnull=True)
        if options["user_surveys"]:
            orphans = orphans.filter(user_survey_id__in=options["user_surveys"])
        orphans = list(orphans.select_related("user_survey"))

        if not orphans:
            self.stdout.write(self.style.SUCCESS("No sectionless snapshot questions."))
            return

        # origin_id -> the source question's section, for the ones still present
        source_sections = dict(
            Question.objects.filter(
                id__in={q.origin_id for q in orphans if q.origin_id is not None}
            ).values_list("id", "section_id")
        )

        recoverable, unsectioned, unresolved = [], [], []
        for orphan in orphans:
            source_section_id = source_sections.get(orphan.origin_id)
            if orphan.origin_id is None or orphan.origin_id not in source_sections:
                unresolved.append(orphan)
            elif source_section_id is None:
                unsectioned.append(orphan)
            else:
                snapshot_section = UserSection.objects.filter(
                    user_survey_id=orphan.user_survey_id, origin_id=source_section_id
                ).first()
                if snapshot_section is None:
                    unresolved.append(orphan)
                else:
                    recoverable.append((orphan, snapshot_section))

        self._report("recoverable — source section still known", recoverable)
        self._report("unsectioned at source — nothing to relink", unsectioned)
        self._report("unresolved — source question or section is gone", unresolved)

        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING("\nDry run. Re-run with --apply to write the repairs.")
            )
            return

        with transaction.atomic():
            for orphan, snapshot_section in recoverable:
                orphan.section = snapshot_section
            UserQuestion.objects.bulk_update(
                [orphan for orphan, _ in recoverable], ["section"], batch_size=500
            )
        self.stdout.write(self.style.SUCCESS(f"\nRelinked {len(recoverable)} question(s)."))

    def _report(self, title, rows):
        entries = [row[0] if isinstance(row, tuple) else row for row in rows]
        self.stdout.write(f"\n{title}: {len(entries)}")
        attempts = sorted({entry.user_survey_id for entry in entries})
        if attempts:
            shown = ", ".join(str(attempt) for attempt in attempts[:20])
            more = "" if len(attempts) <= 20 else f" (+{len(attempts) - 20} more)"
            self.stdout.write(f"  attempts: {shown}{more}")
