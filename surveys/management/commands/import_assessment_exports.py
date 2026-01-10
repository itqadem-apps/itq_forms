from pathlib import Path

from django.core.management import BaseCommand, CommandError, call_command


class Command(BaseCommand):
    help = "Import assessment export fixtures in dependency order."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            default="assessment_exports",
            help="Directory containing export fixtures (default: assessment_exports).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the fixture load order without importing.",
        )

    def handle(self, *args, **options):
        base_path = Path(options["path"]).resolve()
        if not base_path.exists():
            raise CommandError(f"Export directory not found: {base_path}")

        load_order = [
            "users_user.json",
            "sponsors_sponsor.json",
            "classifications_category.json",
            "classifications_tag.json",
            "classifications_modeltag.json",
            "blogs_blog.json",
            "children_child.json",
            "media_library_medialibrary.json",
            "assessments_assessment.json",
            "assessments_section.json",
            "assessments_question.json",
            "assessments_answerschema.json",
            "assessments_classification.json",
            "assessments_answerschemaoption.json",
            "assessments_action.json",
            "assessments_recommendation.json",
            "assessments_userassessment.json",
            "assessments_useranswer.json",
            "assessments_userassessmentclassification.json",
        ]

        missing = [name for name in load_order if not (base_path / name).exists()]
        if missing:
            missing_list = ", ".join(missing)
            raise CommandError(f"Missing fixture files: {missing_list}")

        for name in load_order:
            fixture_path = base_path / name
            if options["dry_run"]:
                self.stdout.write(f"Dry run: {fixture_path}")
                continue
            self.stdout.write(f"Loading {fixture_path}...")
            call_command("loaddata", str(fixture_path))
