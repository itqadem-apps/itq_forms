"""Renumber every survey's questions 1..N across the survey, and every open learner snapshot with
them (story survey-flow 1.6, `forms:AD-4`, `forms:AD-14`).

Exactly one of `--dry-run` or `--apply` is required. `--dry-run` writes nothing; it prints, for
every survey and every open (unsubmitted) snapshot that would change, the resulting sequence:

    survey 12: 7 of 9 questions renumbered, 2 sections re-ranked
        1. question 345  section 7     was 1
        2. question 346  section 7     was 2
        3. question 350  section 8     was 1    <- moves

`was` is the order the row holds now and the left-hand number the one it will hold; `<- moves`
marks a row whose order changes. The listed sequence IS the rendered order, before and after —
the command checks that for every owner, both under the flat reader (`flat_question_ids`) and
under `(order, id)`, which `Question.Meta.ordering` reads once it flips to `["order"]`.

An owner whose rendered order would change is listed as `REFUSED` with its reason and is not
written, even under `--apply` (which then exits non-zero after writing every other owner).
Re-running is safe: an owner already numbered 1..N plans no change and is not listed.

`--allow-render-change` (with `--apply` and `--survey`) writes named refused surveys anyway, in
the order the legacy key gives — what any author save on that survey would do today.

`--json` prints one JSON object per owner instead, for diffing two dry runs.

Submitted snapshots are never written; the summary reports how many were left alone.
"""

import json

from django.core.management.base import BaseCommand, CommandError

from surveys import order_backfill


class Command(BaseCommand):
    help = "Renumber question order 1..N across each survey and each open learner snapshot."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--dry-run", action="store_true", help="Report what would change; write nothing.")
        mode.add_argument("--apply", action="store_true", help="Write the renumber.")
        parser.add_argument(
            "--survey", type=int, action="append", dest="surveys",
            help="Limit to one survey and its open snapshots. Repeatable.",
        )
        parser.add_argument(
            "--allow-render-change", action="store_true",
            help="With --apply and --survey: write named surveys even if their rendered order changes.",
        )
        parser.add_argument("--json", action="store_true", help="One JSON object per owner.")

    def handle(self, *args, **options):
        apply = options["apply"]
        if options["allow_render_change"] and not (apply and options["surveys"]):
            raise CommandError("--allow-render-change needs --apply and at least one --survey.")

        as_json = options["json"]
        report = self._json if as_json else self._text
        counts = order_backfill.run(
            apply=apply,
            only_surveys=options["surveys"],
            allow_render_change=options["allow_render_change"],
            report=report,
        )
        self._summary(counts, apply, options["surveys"], as_json)
        if apply and counts["refused"]:
            raise CommandError(f"{len(counts['refused'])} owner(s) refused and left as they were; every other owner was written.")

    def _text(self, plan):
        if not plan.affected and not plan.refused_reason:
            return
        label = "survey" if plan.kind == "survey" else "open snapshot"
        changes = plan.changes
        head = f"{label} {plan.owner_id}: {len(changes)} of {len(plan.sequence)} questions renumbered"
        if plan.kind == "survey":
            head += f", {plan.sections_reranked} sections re-ranked"
        if plan.refused_reason:
            head = f"REFUSED {head} — {plan.refused_reason}"
        self.stdout.write(head)
        moving = {pk for pk, _, _ in changes}
        for i, pk in enumerate(plan.sequence, start=1):
            section_id, _, order = plan.rows[pk]
            section = f"section {section_id}" if section_id is not None else "no section"
            mark = "    <- moves" if pk in moving else ""
            self.stdout.write(f"    {i:>4}. question {pk:<8} {section:<16} was {order}{mark}")
        if plan.refused_reason:
            self.stdout.write(f"    rendered now: {plan.before}")

    def _json(self, plan):
        self.stdout.write(json.dumps({
            "kind": plan.kind,
            "id": plan.owner_id,
            "affected": plan.affected,
            "refused": plan.refused_reason or None,
            "sections_reranked": plan.sections_reranked,
            "sequence": [
                {"position": i, "question": pk, "section": plan.rows[pk][0], "was": plan.rows[pk][2]}
                for i, pk in enumerate(plan.sequence, start=1)
            ],
            "rendered_before": plan.before,
        }))

    def _summary(self, counts, apply, surveys, as_json):
        from surveys.models import Question
        from user_surveys.models import UserSurvey

        submitted = UserSurvey.objects.filter(submitted_at__isnull=False)
        sectionless_survey = Question.objects.filter(survey_id__isnull=True)
        if surveys:
            submitted = submitted.filter(survey_id__in=surveys)
            sectionless_survey = sectionless_survey.none()
        summary = {
            **{k: v for k, v in counts.items() if k != "refused"},
            "submitted_snapshots_untouched": submitted.count(),
            "questions_without_survey_not_renumbered": sectionless_survey.count(),
            "mode": "apply" if apply else "dry-run",
        }
        if as_json:
            self.stdout.write(json.dumps({"summary": summary}))
            return
        self.stdout.write("")
        self.stdout.write("Applied." if apply else "Dry run — nothing written.")
        self.stdout.write(
            f"surveys: {counts['surveys']} scanned, {counts['surveys_affected']} renumbered, "
            f"{counts['surveys_refused']} refused"
        )
        self.stdout.write(
            f"open snapshots: {counts['snapshots']} scanned, {counts['snapshots_affected']} renumbered, "
            f"{counts['snapshots_refused']} refused"
        )
        self.stdout.write(f"submitted snapshots: {summary['submitted_snapshots_untouched']}, not touched")
        self.stdout.write(
            f"questions with no survey (not renumbered): {summary['questions_without_survey_not_renumbered']}"
        )
