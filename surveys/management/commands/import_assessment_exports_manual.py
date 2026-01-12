from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.management import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_datetime, parse_duration

from surveys.models import (
    Action,
    AnswerSchema,
    AnswerSchemaOption,
    Classification,
    Question,
    Recommendation,
    Section,
    Status,
    Survey,
    SurveyMediaAsset,
)
from survey_collections.models import SurveyCollection
from taxonomy.models import Category, CategoryTranslation
from user_surveys.models import (
    UserAnswer,
    UserAssessment,
    UserAssessmentClassification,
)


@dataclass
class UnmappedReport:
    files: set[str] = field(default_factory=set)
    fields: dict[str, dict[int, list[str]]] = field(default_factory=lambda: defaultdict(dict))
    values: dict[str, set[Any]] = field(default_factory=lambda: defaultdict(set))
    ignored: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    def add_fields(self, file_name: str, pk: int, fields: set[str]) -> None:
        self.fields[file_name][pk] = sorted(fields)

    def add_value(self, key: str, value: Any) -> None:
        self.values[key].add(value)

    def has_issues(self) -> bool:
        return bool(self.files or self.fields or self.values)


def load_fixture(path: Path) -> list[dict[str, Any]]:
    import json

    with path.open() as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise CommandError(f"Fixture is not a list: {path}")
    return data


def parse_dt(value: Any):
    if not value:
        return None
    return parse_datetime(value)


def parse_td(value: Any):
    if not value:
        return None
    return parse_duration(value)


class Command(BaseCommand):
    help = "Import assessment export JSON data with explicit field mapping."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            default="assessment_exports",
            help="Directory containing export JSON files (default: assessment_exports).",
        )
        parser.add_argument(
            "--allow-unmapped",
            action="store_true",
            help="Proceed even when unmapped fields or values are detected.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate and report without writing data.",
        )

    def handle(self, *args, **options):
        base_path = Path(options["path"]).resolve()
        if not base_path.exists():
            raise CommandError(f"Export directory not found: {base_path}")

        report = UnmappedReport()

        files = {
            "assessments_assessment.json": load_fixture(base_path / "assessments_assessment.json"),
            "assessments_section.json": load_fixture(base_path / "assessments_section.json"),
            "assessments_question.json": load_fixture(base_path / "assessments_question.json"),
            "assessments_answerschema.json": load_fixture(base_path / "assessments_answerschema.json"),
            "assessments_classification.json": load_fixture(base_path / "assessments_classification.json"),
            "assessments_answerschemaoption.json": load_fixture(base_path / "assessments_answerschemaoption.json"),
            "assessments_action.json": load_fixture(base_path / "assessments_action.json"),
            "assessments_recommendation.json": load_fixture(base_path / "assessments_recommendation.json"),
            "assessments_userassessment.json": load_fixture(base_path / "assessments_userassessment.json"),
            "assessments_useranswer.json": load_fixture(base_path / "assessments_useranswer.json"),
            "assessments_userassessmentclassification.json": load_fixture(
                base_path / "assessments_userassessmentclassification.json"
            ),
            "blogs_blog.json": load_fixture(base_path / "blogs_blog.json"),
            "classifications_category.json": load_fixture(base_path / "classifications_category.json"),
            "media_library_medialibrary.json": load_fixture(base_path / "media_library_medialibrary.json"),
        }

        # Optional exports from other apps are intentionally ignored:
        # children_child.json, classifications_tag.json, classifications_modeltag.json, sponsors_sponsor.json

        ignored_fields = {
            "assessments_assessment.json": {"deleted_at", "content_type", "object_id"},
            "assessments_section.json": {"deleted_at", "submit_action", "submit_action_target"},
            "assessments_question.json": {"deleted_at"},
            "assessments_userassessment.json": {"price"},
            "blogs_blog.json": {"course"},
            "classifications_category.json": {"parent", "lft", "rght", "level", "created_at", "updated_at"},
            "media_library_medialibrary.json": {
                "file",
                "file_name",
                "mime_type",
                "size",
                "caption",
                "to_delete",
                "is_temp",
                "order",
            },
        }
        for file_name, fields in ignored_fields.items():
            report.ignored[file_name].update(fields)

        assessment_fields = {
            "created_at",
            "deleted_at",
            "category",
            "price",
            "sponsor",
            "title",
            "description",
            "short_description",
            "language",
            "status",
            "assessment_type",
            "display_option",
            "is_timed",
            "is_for_child",
            "is_evaluable",
            "evaluation_type",
            "use_score",
            "use_classifications",
            "use_recommendations",
            "use_actions",
            "allow_end_based_on_answer_repeat",
            "answers_count_to_end",
            "end_based_on_answer_repeat_in_row",
            "allow_update_answer_options_scores_based_on_classification",
            "allow_update_answer_options_text_based_on_classification",
            "create_option_for_each_classification",
            "updated_at",
            "content_type",
            "object_id",
        }
        section_fields = {
            "created_at",
            "title",
            "description",
            "assessment",
            "order",
            "is_hidden",
            "cover",
            "submit_action",
            "submit_action_target",
            "deleted_at",
            "updated_at",
        }
        question_fields = {
            "created_at",
            "title",
            "description",
            "answer_time",
            "assessment",
            "section",
            "order",
            "is_required",
            "type",
            "cover",
            "deleted_at",
            "updated_at",
        }
        schema_fields = {"assessment", "section", "question", "type", "with_file", "is_mcq", "is_grid"}
        classification_fields = {
            "created_at",
            "deleted_at",
            "name",
            "assessment",
            "score",
            "updated_at",
        }
        option_fields = {
            "assessment",
            "section",
            "question",
            "schema",
            "text",
            "score",
            "classification",
            "image",
            "is_row",
            "is_column",
            "ending_option",
            "order",
        }
        action_fields = {"title", "description", "assessment", "upper_limit", "lower_limit"}
        recommendation_fields = {
            "created_at",
            "deleted_at",
            "description",
            "assessment",
            "option",
            "updated_at",
        }
        blog_fields = {
            "status",
            "privacy_status",
            "title",
            "description",
            "short_description",
            "slug",
            "language",
            "created_at",
            "updated_at",
            "deleted_at",
            "category",
            "price",
            "video_list",
            "sponsor",
            "type",
            "course",
            "author",
            "subscribers",
            "enrolled_users",
        }
        category_fields = {
            "created_at",
            "name",
            "slug",
            "parent",
            "updated_at",
            "lft",
            "rght",
            "tree_id",
            "level",
        }
        media_fields = {
            "content_type",
            "object_id",
            "uuid",
            "collection_name",
            "file",
            "file_name",
            "mime_type",
            "size",
            "caption",
            "to_delete",
            "is_temp",
            "order",
        }
        user_assessment_fields = {
            "price",
            "is_paid",
            "assessment",
            "user",
            "child",
            "count_of_ending_options",
            "evaluated_at",
            "submitted_at",
            "score",
            "progress",
            "last_question",
            "action",
        }
        user_answer_fields = {
            "assessment",
            "user",
            "question",
            "question_title",
            "user_assessment",
            "answer",
            "type",
            "score",
            "order",
            "selected_options",
        }
        user_assessment_class_fields = {"user_assessment", "classification", "count"}

        for item in files["assessments_assessment.json"]:
            extra = set(item["fields"]) - assessment_fields
            if extra:
                report.add_fields("assessments_assessment.json", item["pk"], extra)
        for item in files["assessments_section.json"]:
            extra = set(item["fields"]) - section_fields
            if extra:
                report.add_fields("assessments_section.json", item["pk"], extra)
        for item in files["assessments_question.json"]:
            extra = set(item["fields"]) - question_fields
            if extra:
                report.add_fields("assessments_question.json", item["pk"], extra)
        for item in files["assessments_answerschema.json"]:
            extra = set(item["fields"]) - schema_fields
            if extra:
                report.add_fields("assessments_answerschema.json", item["pk"], extra)
        for item in files["assessments_classification.json"]:
            extra = set(item["fields"]) - classification_fields
            if extra:
                report.add_fields("assessments_classification.json", item["pk"], extra)
        for item in files["assessments_answerschemaoption.json"]:
            extra = set(item["fields"]) - option_fields
            if extra:
                report.add_fields("assessments_answerschemaoption.json", item["pk"], extra)
        for item in files["assessments_action.json"]:
            extra = set(item["fields"]) - action_fields
            if extra:
                report.add_fields("assessments_action.json", item["pk"], extra)
        for item in files["assessments_recommendation.json"]:
            extra = set(item["fields"]) - recommendation_fields
            if extra:
                report.add_fields("assessments_recommendation.json", item["pk"], extra)
        for item in files["blogs_blog.json"]:
            extra = set(item["fields"]) - blog_fields
            if extra:
                report.add_fields("blogs_blog.json", item["pk"], extra)
        for item in files["classifications_category.json"]:
            extra = set(item["fields"]) - category_fields
            if extra:
                report.add_fields("classifications_category.json", item["pk"], extra)
        for item in files["media_library_medialibrary.json"]:
            extra = set(item["fields"]) - media_fields
            if extra:
                report.add_fields("media_library_medialibrary.json", item["pk"], extra)
        for item in files["assessments_userassessment.json"]:
            extra = set(item["fields"]) - user_assessment_fields
            if extra:
                report.add_fields("assessments_userassessment.json", item["pk"], extra)
        for item in files["assessments_useranswer.json"]:
            extra = set(item["fields"]) - user_answer_fields
            if extra:
                report.add_fields("assessments_useranswer.json", item["pk"], extra)
        for item in files["assessments_userassessmentclassification.json"]:
            extra = set(item["fields"]) - user_assessment_class_fields
            if extra:
                report.add_fields("assessments_userassessmentclassification.json", item["pk"], extra)

        if report.has_issues() and not options["allow_unmapped"] and not options["dry_run"]:
            summary_lines = []
            if report.files:
                summary_lines.append(f"Unmapped files present: {', '.join(sorted(report.files))}")
            if report.fields:
                for file_name, items in report.fields.items():
                    sample = list(items.items())[:5]
                    sample_txt = ", ".join(f"{pk}: {fields}" for pk, fields in sample)
                    summary_lines.append(f"Extra fields in {file_name} (sample): {sample_txt}")
            if report.values:
                for key, values in report.values.items():
                    sample_vals = list(values)[:10]
                    summary_lines.append(f"Unmapped values for {key}: {sample_vals}")
            raise CommandError("Unmapped data detected. " + " | ".join(summary_lines))

        UserModel = get_user_model()
        user_by_email: dict[str, str] = {}

        user_file = base_path / "users_user.json"
        if user_file.exists():
            user_data = load_fixture(user_file)
            user_field_names = {field.name for field in UserModel._meta.fields}
            for item in user_data:
                fields = item["fields"]
                username = fields.get("username") or fields.get("email")
                email = fields.get("email") or username
                keycloak_sub = fields.get("keycloak_sub") or fields.get("id")
                defaults = {}
                if "username" in user_field_names and username:
                    defaults["username"] = username
                if "email" in user_field_names and email:
                    defaults["email"] = email
                if "first_name" in user_field_names:
                    defaults["first_name"] = fields.get("first_name")
                if "last_name" in user_field_names:
                    defaults["last_name"] = fields.get("last_name")
                if "password" in user_field_names:
                    defaults["password"] = fields.get("password")
                if "is_superuser" in user_field_names:
                    defaults["is_superuser"] = fields.get("is_superuser", False)
                if "is_staff" in user_field_names:
                    defaults["is_staff"] = fields.get("is_staff", False)
                if "is_active" in user_field_names:
                    defaults["is_active"] = fields.get("is_active", True)
                if "last_login" in user_field_names:
                    defaults["last_login"] = parse_dt(fields.get("last_login"))
                if "date_joined" in user_field_names:
                    defaults["date_joined"] = parse_dt(fields.get("date_joined"))

                lookup = {}
                if "id" in user_field_names and keycloak_sub:
                    lookup["id"] = keycloak_sub
                elif "username" in user_field_names and username:
                    lookup["username"] = username
                elif "email" in user_field_names and email:
                    lookup["email"] = email
                else:
                    raise CommandError("User model has no id/username/email field to map.")

                user_obj, _created = UserModel.objects.get_or_create(defaults=defaults, **lookup)
                if email:
                    user_by_email[email] = user_obj.pk
                if keycloak_sub:
                    user_by_email[keycloak_sub] = user_obj.pk

        category_map: dict[int, str] = {}
        tree_map: dict[int, str] = {}
        categories = []
        translations = []
        for item in files["classifications_category.json"]:
            fields = item["fields"]
            name_map = fields.get("name") or {}
            lang = None
            name = None
            if name_map:
                lang, name = next(iter(name_map.items()))
            source_tree = fields.get("tree_id")
            if source_tree is not None and source_tree not in tree_map:
                tree_map[source_tree] = uuid4()
            category = Category(
                category_id=uuid4(),
                tree_id=tree_map.get(source_tree, uuid4()),
                name=name,
                path_text=None,
            )
            categories.append(category)
            category_map[item["pk"]] = category.category_id
            if lang and name:
                translations.append(
                    CategoryTranslation(category=category, language=lang, name=name, slug=fields.get("slug"))
                )

        survey_status_map: dict[int, str] = {}
        surveys = []
        for item in files["assessments_assessment.json"]:
            fields = item["fields"]
            survey_status_map[item["pk"]] = fields.get("status")
            category_uuid = category_map.get(fields.get("category"))
            surveys.append(
                Survey(
                    id=item["pk"],
                    title=fields.get("title"),
                    description=fields.get("description"),
                    short_description=fields.get("short_description"),
                    language=fields.get("language"),
                    assessment_type=fields.get("assessment_type"),
                    display_option=fields.get("display_option"),
                    is_timed=fields.get("is_timed", False),
                    assignable_to_user=fields.get("is_for_child", False),
                    is_evaluable=fields.get("is_evaluable", False),
                    evaluation_type=fields.get("evaluation_type"),
                    use_score=fields.get("use_score", False),
                    use_classifications=fields.get("use_classifications", False),
                    use_recommendations=fields.get("use_recommendations", False),
                    use_actions=fields.get("use_actions", False),
                    allow_end_based_on_answer_repeat=fields.get(
                        "allow_end_based_on_answer_repeat", False
                    ),
                    answers_count_to_end=fields.get("answers_count_to_end", 0),
                    end_based_on_answer_repeat_in_row=fields.get(
                        "end_based_on_answer_repeat_in_row", False
                    ),
                    allow_update_answer_options_scores_based_on_classification=fields.get(
                        "allow_update_answer_options_scores_based_on_classification", False
                    ),
                    allow_update_answer_options_text_based_on_classification=fields.get(
                        "allow_update_answer_options_text_based_on_classification", False
                    ),
                    create_option_for_each_classification=fields.get(
                        "create_option_for_each_classification", False
                    ),
                    created_at=parse_dt(fields.get("created_at")),
                    updated_at=parse_dt(fields.get("updated_at")),
                    category_id=category_uuid,
                    sponsor=fields.get("sponsor"),
                    price=fields.get("price", 0),
                )
            )

        sections = []
        for item in files["assessments_section.json"]:
            fields = item["fields"]
            sections.append(
                Section(
                    id=item["pk"],
                    title=fields.get("title"),
                    description=fields.get("description"),
                    survey_id=fields.get("assessment"),
                    order=fields.get("order"),
                    is_hidden=fields.get("is_hidden", False),
                    cover_asset_id=fields.get("cover") or None,
                    created_at=parse_dt(fields.get("created_at")),
                    updated_at=parse_dt(fields.get("updated_at")),
                )
            )

        questions = []
        for item in files["assessments_question.json"]:
            fields = item["fields"]
            questions.append(
                Question(
                    id=item["pk"],
                    title=fields.get("title"),
                    description=fields.get("description"),
                    answer_time=parse_td(fields.get("answer_time")),
                    survey_id=fields.get("assessment"),
                    section_id=fields.get("section"),
                    order=fields.get("order"),
                    is_required=fields.get("is_required", False),
                    type=fields.get("type"),
                    cover_asset_id=fields.get("cover") or None,
                    created_at=parse_dt(fields.get("created_at")),
                    updated_at=parse_dt(fields.get("updated_at")),
                )
            )

        schemas = []
        for item in files["assessments_answerschema.json"]:
            fields = item["fields"]
            schemas.append(
                AnswerSchema(
                    id=item["pk"],
                    survey_id=fields.get("assessment"),
                    section_id=fields.get("section"),
                    question_id=fields.get("question"),
                    type=fields.get("type"),
                    with_file=fields.get("with_file", False),
                    is_mcq=fields.get("is_mcq", False),
                    is_grid=fields.get("is_grid", False),
                )
            )

        classifications = []
        for item in files["assessments_classification.json"]:
            fields = item["fields"]
            classifications.append(
                Classification(
                    id=item["pk"],
                    name=fields.get("name"),
                    survey_id=fields.get("assessment"),
                    score=fields.get("score"),
                    created_at=parse_dt(fields.get("created_at")),
                    updated_at=parse_dt(fields.get("updated_at")),
                    deleted_at=parse_dt(fields.get("deleted_at")),
                )
            )

        schema_options = []
        for item in files["assessments_answerschemaoption.json"]:
            fields = item["fields"]
            schema_options.append(
                AnswerSchemaOption(
                    id=item["pk"],
                    survey_id=fields.get("assessment"),
                    section_id=fields.get("section"),
                    question_id=fields.get("question"),
                    schema_id=fields.get("schema"),
                    text=fields.get("text"),
                    score=fields.get("score"),
                    classification_id=fields.get("classification"),
                    image_asset_id=fields.get("image") or None,
                    is_row=fields.get("is_row"),
                    is_column=fields.get("is_column"),
                    ending_option=fields.get("ending_option"),
                    order=fields.get("order") or 1,
                )
            )

        actions = []
        for item in files["assessments_action.json"]:
            fields = item["fields"]
            actions.append(
                Action(
                    id=item["pk"],
                    title=fields.get("title"),
                    description=fields.get("description"),
                    survey_id=fields.get("assessment"),
                    upper_limit=fields.get("upper_limit", 0),
                    lower_limit=fields.get("lower_limit", 0),
                )
            )

        recommendations = []
        for item in files["assessments_recommendation.json"]:
            fields = item["fields"]
            recommendations.append(
                Recommendation(
                    id=item["pk"],
                    description=fields.get("description"),
                    survey_id=fields.get("assessment"),
                    option_id=fields.get("option"),
                    created_at=parse_dt(fields.get("created_at")),
                    updated_at=parse_dt(fields.get("updated_at")),
                    deleted_at=parse_dt(fields.get("deleted_at")),
                )
            )

        collection_surveys = []
        collection_subscribers: list[tuple[SurveyCollection, list[Any]]] = []
        collection_enrolled: list[tuple[SurveyCollection, list[Any]]] = []
        for item in files["blogs_blog.json"]:
            fields = item["fields"]
            title_map = fields.get("title") or {}
            description_map = fields.get("description") or {}
            short_map = fields.get("short_description") or {}
            lang = None
            if title_map:
                lang = next(iter(title_map.keys()))
            elif description_map:
                lang = next(iter(description_map.keys()))
            elif short_map:
                lang = next(iter(short_map.keys()))
            else:
                lang = fields.get("language")

            title = title_map.get(lang) if lang else None
            if title is None and title_map:
                title = next(iter(title_map.values()))
            description = description_map.get(lang) if lang else None
            if description is None and description_map:
                description = next(iter(description_map.values()))
            short_description = short_map.get(lang) if lang else None
            if short_description is None and short_map:
                short_description = next(iter(short_map.values()))

            author_value = fields.get("author")
            author_id = None
            if isinstance(author_value, list):
                author_value = author_value[0] if author_value else None
            if isinstance(author_value, str) and author_value in user_by_email:
                author_id = user_by_email[author_value]
            elif author_value is not None:
                report.add_value("blogs.author", author_value)

            collection = SurveyCollection(
                status=fields.get("status"),
                privacy_status=fields.get("privacy_status"),
                title=title,
                description=description,
                short_description=short_description,
                slug=fields.get("slug"),
                language=lang,
                created_at=parse_dt(fields.get("created_at")),
                updated_at=parse_dt(fields.get("updated_at")),
                deleted_at=parse_dt(fields.get("deleted_at")),
                category_id=category_map.get(fields.get("category")),
                price=fields.get("price", 0),
                video_list=fields.get("video_list"),
                sponsor=fields.get("sponsor"),
                type=fields.get("type"),
                author_id=author_id,
            )
            collection_surveys.append(collection)
            collection_subscribers.append((collection, fields.get("subscribers") or []))
            collection_enrolled.append((collection, fields.get("enrolled_users") or []))

        assets = []
        asset_type_map = {"thumb": "thumbnail", "cover": "cover"}
        for item in files["media_library_medialibrary.json"]:
            fields = item["fields"]
            ct = fields.get("content_type") or []
            if tuple(ct) != ("assessments", "assessment"):
                report.add_value("media_library.content_type", tuple(ct))
                continue
            asset_type = asset_type_map.get(fields.get("collection_name"))
            if not asset_type:
                report.add_value("media_library.collection_name", fields.get("collection_name"))
                continue
            assets.append(
                SurveyMediaAsset(
                    survey_id=fields.get("object_id"),
                    asset_id=fields.get("uuid"),
                    asset_type=asset_type,
                )
            )

        user_assessments = []
        for item in files["assessments_userassessment.json"]:
            fields = item["fields"]
            user_ref_list = fields.get("user") or []
            user_ref = user_ref_list[0] if user_ref_list else None
            user_id = user_by_email.get(user_ref) if user_ref else None
            if user_ref and user_id is None:
                report.add_value("userassessment.user", user_ref)
            user_assessments.append(
                UserAssessment(
                    id=item["pk"],
                    is_paid=fields.get("is_paid", False),
                    survey_id=fields.get("assessment"),
                    user_id=user_id,
                    child_id=str(fields.get("child")) if fields.get("child") is not None else None,
                    count_of_ending_options=fields.get("count_of_ending_options", 0),
                    evaluated_at=parse_dt(fields.get("evaluated_at")),
                    submitted_at=parse_dt(fields.get("submitted_at")),
                    score=fields.get("score"),
                    progress=fields.get("progress"),
                    last_question_id=fields.get("last_question"),
                    action_id=fields.get("action"),
                )
            )

        user_answers = []
        user_answer_selected = []
        for item in files["assessments_useranswer.json"]:
            fields = item["fields"]
            user_ref_list = fields.get("user") or []
            user_ref = user_ref_list[0] if user_ref_list else None
            user_id = user_by_email.get(user_ref) if user_ref else None
            if user_ref and user_id is None:
                report.add_value("useranswer.user", user_ref)
            user_answers.append(
                UserAnswer(
                    id=item["pk"],
                    survey_id=fields.get("assessment"),
                    user_id=user_id,
                    question_id=fields.get("question"),
                    question_title=fields.get("question_title"),
                    user_assessment_id=fields.get("user_assessment"),
                    answer=fields.get("answer"),
                    type=fields.get("type"),
                    score=fields.get("score"),
                    order=fields.get("order"),
                )
            )
            for option_id in fields.get("selected_options") or []:
                user_answer_selected.append((item["pk"], option_id))

        user_assessment_classifications = []
        for item in files["assessments_userassessmentclassification.json"]:
            fields = item["fields"]
            user_assessment_classifications.append(
                UserAssessmentClassification(
                    id=item["pk"],
                    user_assessment_id=fields.get("user_assessment"),
                    classification_id=fields.get("classification"),
                    count=fields.get("count", 0),
                )
            )

        if report.has_issues() and not options["allow_unmapped"] and not options["dry_run"]:
            summary_lines = []
            if report.values:
                for key, values in report.values.items():
                    sample_vals = list(values)[:10]
                    summary_lines.append(f"Unmapped values for {key}: {sample_vals}")
            raise CommandError("Unmapped reference values detected. " + " | ".join(summary_lines))

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run: no data written."))
            counts = [
                ("categories", len(categories)),
                ("category_translations", len(translations)),
                ("surveys", len(surveys)),
                ("sections", len(sections)),
                ("questions", len(questions)),
                ("answer_schemas", len(schemas)),
                ("classifications", len(classifications)),
                ("answer_schema_options", len(schema_options)),
                ("actions", len(actions)),
                ("recommendations", len(recommendations)),
                ("survey_media_assets", len(assets)),
                ("survey_collections", len(collection_surveys)),
                ("user_assessments", len(user_assessments)),
                ("user_answers", len(user_answers)),
                ("user_assessment_classifications", len(user_assessment_classifications)),
                ("user_answer_selected", len(user_answer_selected)),
            ]
            for label, count in counts:
                self.stdout.write(self.style.SUCCESS(f"OK {label}: {count}"))
            if report.has_issues():
                self.stdout.write(self.style.ERROR("Not OK: unmapped data detected."))
                if report.files:
                    self.stdout.write(f"Unmapped files: {', '.join(sorted(report.files))}")
                if report.fields:
                    for file_name, items in report.fields.items():
                        sample = list(items.items())[:5]
                        sample_txt = ", ".join(f"{pk}: {fields}" for pk, fields in sample)
                        self.stdout.write(
                            f"Extra fields in {file_name} ({len(items)} items, sample): {sample_txt}"
                        )
                if report.values:
                    for key, values in report.values.items():
                        sample_vals = list(values)[:10]
                        self.stdout.write(
                            f"Unmapped values for {key} ({len(values)} values, sample): {sample_vals}"
                        )
            else:
                self.stdout.write(self.style.SUCCESS("No unmapped fields or values detected."))
            return

        with transaction.atomic():
            Category.objects.bulk_create(categories, batch_size=500)
            if translations:
                CategoryTranslation.objects.bulk_create(translations, batch_size=500)

            Survey.objects.bulk_create(surveys, batch_size=500)
            Section.objects.bulk_create(sections, batch_size=500)
            Question.objects.bulk_create(questions, batch_size=500)
            AnswerSchema.objects.bulk_create(schemas, batch_size=500)
            Classification.objects.bulk_create(classifications, batch_size=500)
            AnswerSchemaOption.objects.bulk_create(schema_options, batch_size=500)
            Action.objects.bulk_create(actions, batch_size=500)
            Recommendation.objects.bulk_create(recommendations, batch_size=500)
            if assets:
                SurveyMediaAsset.objects.bulk_create(assets, batch_size=500)

            if collection_surveys:
                subscribers_through = SurveyCollection.subscribers.through
                enrolled_through = SurveyCollection.enrolled_users.through
                subscriber_rows = []
                enrolled_rows = []
                for collection in collection_surveys:
                    desired_updated_at = collection.updated_at
                    collection.save()
                    if desired_updated_at:
                        SurveyCollection.objects.filter(id=collection.id).update(
                            updated_at=desired_updated_at
                        )
                for collection, subscribers in collection_subscribers:
                    for value in subscribers:
                        user_id = None
                        if isinstance(value, list):
                            value = value[0] if value else None
                        if isinstance(value, str) and value in user_by_email:
                            user_id = user_by_email[value]
                        elif isinstance(value, int):
                            user_id = value if UserModel.objects.filter(id=value).exists() else None
                        if user_id is None and value is not None:
                            report.add_value("blogs.subscribers", value)
                            continue
                        if user_id is not None:
                            subscriber_rows.append(
                                subscribers_through(
                                    surveycollection_id=collection.id,
                                    user_id=user_id,
                                )
                            )
                for collection, enrolled in collection_enrolled:
                    for value in enrolled:
                        user_id = None
                        if isinstance(value, list):
                            value = value[0] if value else None
                        if isinstance(value, str) and value in user_by_email:
                            user_id = user_by_email[value]
                        elif isinstance(value, int):
                            user_id = value if UserModel.objects.filter(id=value).exists() else None
                        if user_id is None and value is not None:
                            report.add_value("blogs.enrolled_users", value)
                            continue
                        if user_id is not None:
                            enrolled_rows.append(
                                enrolled_through(
                                    surveycollection_id=collection.id,
                                    user_id=user_id,
                                )
                            )
                if subscriber_rows:
                    subscribers_through.objects.bulk_create(subscriber_rows, batch_size=500)
                if enrolled_rows:
                    enrolled_through.objects.bulk_create(enrolled_rows, batch_size=500)

            if user_assessments:
                UserAssessment.objects.bulk_create(user_assessments, batch_size=500)
            if user_answers:
                UserAnswer.objects.bulk_create(user_answers, batch_size=500)
            if user_assessment_classifications:
                UserAssessmentClassification.objects.bulk_create(
                    user_assessment_classifications, batch_size=500
                )

            if user_answer_selected:
                through = UserAnswer.selected_options.through
                through_rows = [
                    through(useranswer_id=ua_id, answerschemaoption_id=opt_id)
                    for ua_id, opt_id in user_answer_selected
                ]
                through.objects.bulk_create(through_rows, batch_size=1000)

            for survey in surveys:
                status_value = survey_status_map.get(survey.id)
                if status_value:
                    status = Status.objects.create(survey_id=survey.id, status=status_value)
                    Survey.objects.filter(id=survey.id).update(status_id=status.id)
            if report.has_issues() and not options["allow_unmapped"]:
                summary_lines = []
                if report.values:
                    for key, values in report.values.items():
                        sample_vals = list(values)[:10]
                        summary_lines.append(f"Unmapped values for {key}: {sample_vals}")
                raise CommandError("Unmapped reference values detected. " + " | ".join(summary_lines))

        self.stdout.write(self.style.SUCCESS("Import completed."))
