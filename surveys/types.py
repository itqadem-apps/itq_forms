from __future__ import annotations

from __future__ import annotations

from typing import List, Optional

import strawberry
import strawberry_django
from strawberry import auto


from .models import (
    AnswerSchema,
    AnswerSchemaOption,
    Classification,
    Question,
    Recommendation,
    Section,
    Survey,
    SurveyMediaAsset,
    Usage,
    Price,
)
from taxonomy.models import Category, CategoryTranslation
from survey_collections.models import SurveyCollection
from app.auth_utils import get_django_user
from user_surveys.models import (
    UserAnswer,
    UserSurvey,
    UserSurveyClassification,
    UserSurveyRecommendation,
)


@strawberry_django.type(Survey)
class SurveyType:
    id: auto
    title: auto
    description: auto
    short_description: auto
    slug: auto
    language: auto
    status_id: auto
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
    allow_update_answer_options_scores_based_on_classification: auto
    allow_update_answer_options_text_based_on_classification: auto
    create_option_for_each_classification: auto
    category_id: auto
    category: Optional["CategoryType"]
    sponsor: auto
    price: auto
    created_at: auto
    updated_at: auto
    sections: List["SectionType"]
    @strawberry.field
    def assets(self, asset_type: str | None = None) -> List["SurveyAssetType"]:
        qs = self.assets.all()
        if asset_type:
            qs = qs.filter(asset_type=asset_type)
        return list(qs)

    @strawberry.field
    def status(self) -> str | None:
        return self.status.status if self.status_id else None

    @strawberry.field
    def user_surveys(self, info) -> List["UserSurveyType"]:
        try:
            django_user = get_django_user(info)
            return list(self.usersurvey_set.filter(user=django_user, submitted_at__isnull=True))
        except ValueError:
            return []

    @strawberry.field
    def is_enrolled(self, info) -> bool:
        try:
            django_user = get_django_user(info)
            return UserSurvey.objects.filter(
                user=django_user,
                survey_id=self.id,
                submitted_at__isnull=True,
            ).exists()
        except ValueError:
            return False

    @strawberry.field
    def usage_used(self, info) -> int:
        try:
            django_user = get_django_user(info)
        except ValueError:
            return 0

        usage = self.usage_set.filter(user=django_user).first()
        user_survey = self.user_surveys(user=django_user)
        if not usage:
            if user_survey: return 1
            else: return 0
        return usage.used_count if usage else 0

    @strawberry.field
    def usage_limit(self, info) -> int:
        try:
            django_user = get_django_user(info)
        except ValueError:
            return 0

        usage = self.usage_set.filter(user=django_user).first()
        if not usage:
            return 1
        return usage.usage_limit or 1

    @strawberry.field
    def prices(self) -> List["PriceType"]:
        return list(self.prices.all())


@strawberry_django.type(Section)
class SectionType:
    id: auto
    title: auto
    description: auto
    survey_id: auto
    order: auto
    is_hidden: auto
    cover_asset_id: auto
    created_at: auto
    updated_at: auto
    questions: List["QuestionType"]


@strawberry_django.type(Question)
class QuestionType:
    id: auto
    title: auto
    description: auto
    survey_id: auto
    section_id: auto
    section: "SectionType"
    order: auto
    is_required: auto
    type: auto
    cover_asset_id: auto
    created_at: auto
    updated_at: auto
    answer_schema: Optional["AnswerSchemaType"]

    @strawberry.field
    def answer_time(self) -> Optional[str]:
        value = self.__dict__.get("answer_time")
        if value is None:
            return None
        return str(value)

    @strawberry.field
    def next_question_id(self) -> Optional[int]:
        survey_id = self.survey_id or (self.section.survey_id if self.section_id else None)
        if not survey_id:
            return None
        ids = list(
            Question.objects.filter(survey_id=survey_id, section__isnull=False)
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
        survey_id = self.survey_id or (self.section.survey_id if self.section_id else None)
        if not survey_id:
            return None
        ids = list(
            Question.objects.filter(survey_id=survey_id, section__isnull=False)
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

    @strawberry.field
    def user_answer(self, info, user_survey_id: Optional[int] = None) -> Optional["UserAnswerType"]:
        django_user = get_django_user(info)
        if user_survey_id is None:
            user_survey_id = getattr(self, "_user_survey_id", None)
        if user_survey_id is None:
            return None
        assessment = UserSurvey.objects.filter(id=user_survey_id, user=django_user).first()
        if not assessment:
            return None
        return UserAnswer.objects.filter(user_survey=assessment, question_id=self.id).first()

    @strawberry.field
    def progress(self, info, user_survey_id: Optional[int] = None) -> Optional[int]:
        django_user = get_django_user(info)
        if user_survey_id is None:
            user_survey_id = getattr(self, "_user_survey_id", None)
        if user_survey_id is None:
            return None
        assessment = UserSurvey.objects.filter(id=user_survey_id, user=django_user).first()
        if not assessment or not assessment.survey_id:
            return None
        total = Question.objects.filter(
            survey_id=assessment.survey_id, section__isnull=False
        ).count()
        if total == 0:
            return 0
        answered = (
            UserAnswer.objects.filter(user_survey=assessment)
            .exclude(answer__isnull=True, selected_options__isnull=True)
            .values_list("question_id", flat=True)
            .distinct()
            .count()
        )
        return int((answered / total) * 100)


@strawberry.type
class FacetValueGQL:
    value: str
    count: int


@strawberry.type
class FacetGQL:
    name: str
    values: List[FacetValueGQL]


@strawberry.type
class SurveyResultsGQL:
    items: List[SurveyType]
    total: int
    facets: List[FacetGQL]


@strawberry.type
class QuestionsFiltersGQL:
    question_ids: Optional[List[int]]
    section_id: Optional[int]
    is_required: Optional[bool]
    question_type: Optional[str]
    answered: Optional[bool]


@strawberry.type
class QuestionsResultsGQL:
    items: List["QuestionType"]
    total: int
    filters: QuestionsFiltersGQL


@strawberry_django.type(SurveyCollection)
class SurveyCollectionType:
    id: auto
    status: auto
    title: auto
    description: auto
    short_description: auto
    slug: auto
    language: auto
    created_at: auto
    updated_at: auto
    deleted_at: auto
    category_id: auto
    price: auto
    sponsor: auto
    type: auto
    assessments: List[SurveyType]


@strawberry_django.type(Category)
class CategoryType:
    category_id: auto
    tree_id: auto
    name: auto
    path_text: auto
    translations: List["CategoryTranslationType"]


@strawberry_django.type(CategoryTranslation)
class CategoryTranslationType:
    id: auto
    language: auto
    name: auto
    slug: auto


@strawberry.type
class SurveyCollectionsResultsGQL:
    items: List[SurveyCollectionType]
    total: int
    facets: List[FacetGQL]


@strawberry.type
class UserSurveysResultsGQL:
    items: List["UserSurveyType"]
    total: int


@strawberry.type
class FinishAssessmentResult:
    status: str
    score: Optional[int]
    evaluated_at: Optional[str]
    classifications: List["UserSurveyClassificationType"]
    recommendations: List["UserSurveyRecommendationType"]


@strawberry_django.type(Classification)
class ClassificationType:
    id: auto
    name: auto
    score: auto


@strawberry_django.type(Recommendation)
class RecommendationType:
    id: auto
    description: auto


@strawberry_django.type(AnswerSchema)
class AnswerSchemaType:
    id: auto
    survey_id: auto
    section_id: auto
    question_id: auto
    type: auto
    with_file: auto
    is_mcq: auto
    is_grid: auto
    options: List["AnswerSchemaOptionType"]


@strawberry_django.type(AnswerSchemaOption)
class AnswerSchemaOptionType:
    id: auto
    survey_id: auto
    section_id: auto
    question_id: auto
    schema_id: auto
    text: auto
    score: auto
    classification_id: auto
    image_asset_id: auto
    is_row: auto
    is_column: auto
    ending_option: auto
    order: auto


@strawberry_django.type(UserSurveyClassification)
class UserSurveyClassificationType:
    id: auto
    user_survey_id: auto
    classification: ClassificationType
    count: auto


@strawberry_django.type(UserSurveyRecommendation)
class UserSurveyRecommendationType:
    id: auto
    user_survey_id: auto
    recommendation: RecommendationType
    count: auto


@strawberry_django.type(UserAnswer)
class UserAnswerType:
    id: auto
    survey_id: auto
    user_id: auto
    question_id: auto
    user_survey_id: auto
    answer: auto
    type: auto
    score: auto
    order: auto


@strawberry_django.type(UserSurvey)
class UserSurveyType:
    id: int
    is_paid: auto
    survey_id: auto
    user_id: auto
    child_id: auto
    count_of_ending_options: auto
    evaluated_at: auto
    submitted_at: auto
    score: auto
    progress: auto
    last_question_id: auto
    action_id: auto


@strawberry_django.type(SurveyMediaAsset)
class SurveyAssetType:
    id: auto
    asset_id: auto
    asset_type: auto


@strawberry_django.type(Price)
class PriceType:
    id: auto
    survey_id: auto
    currency: auto
    amount_cents: auto
    compare_at_amount_cents: auto
