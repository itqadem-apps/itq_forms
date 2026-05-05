from __future__ import annotations

from typing import List, Optional

import strawberry
import strawberry_django
from strawberry import auto
from strawberry.types import Info

from surveys.models import Usage
from surveys.usage_access import FREE_ATTEMPTS, summarize_usage_rows
from app.auth_utils import get_django_user
from accounts.models import Child
from user_surveys.models import (
    UserAction,
    UserAnswer,
    UserAnswerOption,
    UserAnswerSchema,
    UserClassification,
    UserQuestion,
    UserRecommendation,
    UserSection,
    UserSurvey,
    UserSurveyClassification,
    UserSurveyRecommendation,
)


# ── Translation content types ────────────────────────────────────────

@strawberry.type
class SurveyTranslationContent:
    title: Optional[str] = None
    description: Optional[str] = None
    short_description: Optional[str] = None
    slug: Optional[str] = None


@strawberry.type
class SurveyTranslation:
    language: str
    content: SurveyTranslationContent


@strawberry.type
class SectionTranslationContent:
    title: Optional[str] = None
    description: Optional[str] = None


@strawberry.type
class SectionTranslation:
    language: str
    content: SectionTranslationContent


@strawberry.type
class QuestionTranslationContent:
    title: Optional[str] = None
    description: Optional[str] = None


@strawberry.type
class QuestionTranslation:
    language: str
    content: QuestionTranslationContent


@strawberry.type
class OptionTranslationContent:
    text: Optional[str] = None


@strawberry.type
class OptionTranslation:
    language: str
    content: OptionTranslationContent


@strawberry.type
class ClassificationTranslationContent:
    name: Optional[str] = None


@strawberry.type
class ClassificationTranslation:
    language: str
    content: ClassificationTranslationContent


@strawberry.type
class RecommendationTranslationContent:
    description: Optional[str] = None


@strawberry.type
class RecommendationTranslation:
    language: str
    content: RecommendationTranslationContent


@strawberry.type
class ActionTranslationContent:
    title: Optional[str] = None
    description: Optional[str] = None


@strawberry.type
class ActionTranslation:
    language: str
    content: ActionTranslationContent


# ── Helpers ───────────────────────────────────────────────────────────

def _parse_translations(raw: dict, content_cls, translation_cls) -> list:
    if not raw:
        return []
    result = []
    for lang, fields in raw.items():
        if isinstance(fields, dict):
            content = content_cls(**{k: v for k, v in fields.items() if hasattr(content_cls, k)})
            result.append(translation_cls(language=lang, content=content))
    return result


# ── Django-backed types ───────────────────────────────────────────────

@strawberry_django.type(Child)
class ChildType:
    id: auto
    name: auto
    photo_id: auto


@strawberry_django.type(UserSection)
class UserSectionType:
    id: auto
    origin_id: auto
    order: auto
    is_hidden: auto
    cover_asset_id: auto
    submit_action: auto
    submit_action_target_id: auto
    created_at: auto
    updated_at: auto
    questions: List["UserQuestionType"]

    @strawberry.field
    def translations(self) -> List[SectionTranslation]:
        return _parse_translations(
            getattr(self, "translations", None) or {},
            SectionTranslationContent,
            SectionTranslation,
        )


@strawberry_django.type(UserAnswerSchema)
class UserAnswerSchemaType:
    id: auto
    origin_id: auto
    type: auto
    with_file: auto
    is_mcq: auto
    is_grid: auto
    options: List["UserAnswerOptionType"]


@strawberry_django.type(UserAnswerOption)
class UserAnswerOptionType:
    id: auto
    origin_id: auto
    score: auto
    image_asset_id: auto
    is_row: auto
    is_column: auto
    ending_option: auto
    order: auto
    classification: Optional["UserClassificationType"]

    @strawberry.field
    def translations(self) -> List[OptionTranslation]:
        return _parse_translations(
            getattr(self, "translations", None) or {},
            OptionTranslationContent,
            OptionTranslation,
        )


@strawberry_django.type(UserClassification)
class UserClassificationType:
    id: auto
    origin_id: auto
    score: auto

    @strawberry.field
    def translations(self) -> List[ClassificationTranslation]:
        return _parse_translations(
            getattr(self, "translations", None) or {},
            ClassificationTranslationContent,
            ClassificationTranslation,
        )


@strawberry_django.type(UserRecommendation)
class UserRecommendationType:
    id: auto
    origin_id: auto
    option_id: auto

    @strawberry.field
    def translations(self) -> List[RecommendationTranslation]:
        return _parse_translations(
            getattr(self, "translations", None) or {},
            RecommendationTranslationContent,
            RecommendationTranslation,
        )


@strawberry_django.type(UserAction)
class UserActionType:
    id: auto
    origin_id: auto
    upper_limit: auto
    lower_limit: auto

    @strawberry.field
    def translations(self) -> List[ActionTranslation]:
        return _parse_translations(
            getattr(self, "translations", None) or {},
            ActionTranslationContent,
            ActionTranslation,
        )


@strawberry_django.type(UserQuestion)
class UserQuestionType:
    id: auto
    origin_id: auto
    section_id: auto
    order: auto
    is_required: auto
    type: auto
    cover_asset_id: auto
    created_at: auto
    updated_at: auto
    answer_schema: Optional[UserAnswerSchemaType]

    @strawberry.field
    def translations(self) -> List[QuestionTranslation]:
        return _parse_translations(
            getattr(self, "translations", None) or {},
            QuestionTranslationContent,
            QuestionTranslation,
        )

    @strawberry.field
    def answer_time(self) -> Optional[str]:
        value = getattr(self, "answer_time", None)
        if value is None:
            return None
        return str(value)

    @strawberry.field
    def answers(self) -> List["UserAnswerType"]:
        return list(UserAnswer.objects.filter(question_id=self.id))

    @strawberry.field
    def next_question_id(self) -> Optional[int]:
        ids = list(
            UserQuestion.objects.filter(
                user_survey_id=self.user_survey_id, section__isnull=False
            )
            .order_by("section__order", "order")
            .values_list("id", flat=True)
        )
        if not ids:
            return None
        try:
            idx = ids.index(self.id)
        except ValueError:
            return None
        return ids[idx + 1] if idx + 1 < len(ids) else None

    @strawberry.field
    def prev_question_id(self) -> Optional[int]:
        ids = list(
            UserQuestion.objects.filter(
                user_survey_id=self.user_survey_id, section__isnull=False
            )
            .order_by("section__order", "order")
            .values_list("id", flat=True)
        )
        if not ids:
            return None
        try:
            idx = ids.index(self.id)
        except ValueError:
            return None
        return ids[idx - 1] if idx - 1 >= 0 else None


@strawberry_django.type(UserSurvey)
class UserSurveyType:
    id: int
    survey_id: auto
    collection_id: auto
    user_id: auto
    child: Optional[ChildType]

    # snapshot fields
    status: auto
    survey_type: auto
    display_option: auto
    is_timed: auto
    is_for_child: auto
    is_evaluable: auto
    evaluation_type: auto
    use_score: auto
    use_classifications: auto
    use_recommendations: auto
    use_actions: auto
    allow_end_based_on_answer_repeat: auto
    answers_count_to_end: auto
    end_based_on_answer_repeat_in_row: auto
    enable_anti_cheat: auto
    lock_answers: auto
    randomize_questions: auto
    randomize_options: auto
    cover_id: auto
    thumb_id: auto
    category_id_snapshot: auto
    sponsor: auto
    survey_created_at: auto
    survey_updated_at: auto

    # assessment state
    session_token: auto
    started_at: auto
    tab_switch_count: auto
    count_of_ending_options: auto
    termination_reason: auto
    evaluated_at: auto
    submitted_at: auto
    score: auto
    last_question_id: auto
    action_id: auto

    # related snapshot data
    sections: List[UserSectionType]
    questions: List[UserQuestionType]

    @strawberry.field
    def time_limit(self) -> Optional[str]:
        value = getattr(self, "time_limit", None)
        if value is None:
            return None
        return str(value)

    @strawberry.field
    def translations(self) -> List[SurveyTranslation]:
        return _parse_translations(
            getattr(self, "translations", None) or {},
            SurveyTranslationContent,
            SurveyTranslation,
        )

    @strawberry.field
    def actions(self) -> List[UserActionType]:
        if not self.evaluated_at:
            return []
        return list(UserAction.objects.filter(user_survey_id=self.id))

    @strawberry.field
    def survey_classifications(self) -> List[UserSurveyClassificationType]:
        if not self.evaluated_at:
            return []
        return list(UserSurveyClassification.objects.filter(user_survey_id=self.id))

    @strawberry.field
    def survey_recommendations(self) -> List[UserSurveyRecommendationType]:
        if not self.evaluated_at:
            return []
        return list(UserSurveyRecommendation.objects.filter(user_survey_id=self.id))

    @strawberry.field
    def usage_used(self, info: Info) -> int:
        try:
            django_user = get_django_user(info)
        except ValueError:
            return 0
        if django_user.id != self.user_id or not self.survey_id:
            return 0
        usages = list(
            Usage.objects.filter(user_id=django_user.id, survey_id=self.survey_id)
            .order_by("created_at", "id")
        )
        return summarize_usage_rows(usages).total_used

    @strawberry.field
    def usage_limit(self, info: Info) -> int:
        try:
            django_user = get_django_user(info)
        except ValueError:
            return FREE_ATTEMPTS
        if django_user.id != self.user_id or not self.survey_id:
            return FREE_ATTEMPTS
        usages = list(
            Usage.objects.filter(user_id=django_user.id, survey_id=self.survey_id)
            .order_by("created_at", "id")
        )
        summary = summarize_usage_rows(usages)
        if not summary.has_any:
            return FREE_ATTEMPTS
        return summary.total_limit or FREE_ATTEMPTS

    @strawberry.field
    def progress(self, info: Info) -> int:
        try:
            django_user = get_django_user(info)
        except ValueError:
            return 0
        if django_user.id != self.user_id:
            return 0
        total = UserQuestion.objects.filter(
            user_survey_id=self.id, section__isnull=False
        ).count()
        if total == 0:
            return 0
        answered = (
            UserAnswer.objects.filter(user_survey_id=self.id)
            .exclude(answer__isnull=True, selected_options__isnull=True)
            .values_list("question_id", flat=True)
            .distinct()
            .count()
        )
        return int((answered / total) * 100)



@strawberry_django.type(UserAnswer)
class UserAnswerType:
    id: auto
    user_id: auto
    question_id: auto
    user_survey_id: auto
    answer: auto
    type: auto
    score: auto
    order: auto
    answered_at: auto
    selected_options: List[UserAnswerOptionType]

    @strawberry.field
    def time_spent(self) -> Optional[str]:
        value = getattr(self, "time_spent", None)
        if value is None:
            return None
        return str(value)


@strawberry_django.type(UserSurveyClassification)
class UserSurveyClassificationType:
    id: auto
    user_survey_id: auto
    count: auto
    classification: Optional[UserClassificationType]


@strawberry_django.type(UserSurveyRecommendation)
class UserSurveyRecommendationType:
    id: auto
    user_survey_id: auto
    count: auto
    recommendation: Optional[UserRecommendationType]
