from __future__ import annotations

import json
from pathlib import Path

from django.core.management import BaseCommand, CommandError
from django.db import transaction

from surveys.models import AnswerSchemaOption, Section, Survey


DEFAULT_MAPPING = Path(__file__).resolve().parent.parent / "data" / "asset_mapping.json"


class Command(BaseCommand):
    help = (
        "Import asset UUIDs from an exported mapping.json and update "
        "Survey.thumb_id/cover_id, Section.cover_asset_id, "
        "and AnswerSchemaOption.image_asset_id."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "path",
            nargs="?",
            default=None,
            help="Path to mapping.json or directory containing it (default: bundled asset_mapping.json).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be done without writing to the DB.",
        )

    def handle(self, *args, **options):
        if options["path"]:
            path = Path(options["path"]).resolve()
            mapping_file = path if path.is_file() else path / "mapping.json"
        else:
            mapping_file = DEFAULT_MAPPING
        if not mapping_file.exists():
            raise CommandError(f"Mapping file not found at {mapping_file}")

        with open(mapping_file) as f:
            data = json.load(f)

        assets = data.get("assets", [])
        self.stdout.write(f"Found {len(assets)} assets in mapping.json")

        assessment_assets = []
        section_assets = []
        option_assets = []

        for asset in assets:
            rt = asset["target"]["resource_type"]
            if rt == "assessments":
                assessment_assets.append(asset)
            elif rt == "assessment_sections":
                section_assets.append(asset)
            elif rt == "assessment_options":
                option_assets.append(asset)
            else:
                self.stderr.write(f"  Unknown resource_type: {rt}, skipping")

        self.stdout.write(
            f"  assessments: {len(assessment_assets)}, "
            f"sections: {len(section_assets)}, "
            f"options: {len(option_assets)}"
        )

        if options["dry_run"]:
            self._dry_run(assessment_assets, section_assets, option_assets)
        else:
            self._update_db(assessment_assets, section_assets, option_assets)

    def _dry_run(self, assessment_assets, section_assets, option_assets):
        for asset in assessment_assets:
            collection = asset["target"]["collection_name"]
            field = "thumb_id" if collection == "thumb" else "cover_id"
            self.stdout.write(
                f"  Survey id={asset['assessment']['id']} "
                f"SET {field}={asset['uuid']}"
            )
        for asset in section_assets:
            self.stdout.write(
                f"  Section id={asset['section']['id']} "
                f"SET cover_asset_id={asset['uuid']}"
            )
        for asset in option_assets:
            self.stdout.write(
                f"  AnswerSchemaOption id={asset['option']['id']} "
                f"SET image_asset_id={asset['uuid']}"
            )

    def _update_db(self, assessment_assets, section_assets, option_assets):
        with transaction.atomic():
            # Survey thumb_id / cover_id
            survey_updates = {}
            for asset in assessment_assets:
                sid = asset["assessment"]["id"]
                collection = asset["target"]["collection_name"]
                field = "thumb_id" if collection == "thumb" else "cover_id"
                survey_updates.setdefault(sid, {})[field] = asset["uuid"]

            survey_count = 0
            for sid, fields in survey_updates.items():
                if Survey.objects.filter(id=sid).update(**fields):
                    survey_count += 1
                else:
                    self.stderr.write(f"  Survey id={sid} not found")
            self.stdout.write(f"Updated {survey_count} surveys")

            # Section cover_asset_id
            section_count = 0
            for asset in section_assets:
                sec_id = asset["section"]["id"]
                if Section.objects.filter(id=sec_id).update(cover_asset_id=asset["uuid"]):
                    section_count += 1
                else:
                    self.stderr.write(f"  Section id={sec_id} not found")
            self.stdout.write(f"Updated {section_count} sections")

            # AnswerSchemaOption image_asset_id
            option_count = 0
            for asset in option_assets:
                opt_id = asset["option"]["id"]
                if AnswerSchemaOption.objects.filter(id=opt_id).update(image_asset_id=asset["uuid"]):
                    option_count += 1
                else:
                    self.stderr.write(f"  AnswerSchemaOption id={opt_id} not found")
            self.stdout.write(f"Updated {option_count} answer schema options")
