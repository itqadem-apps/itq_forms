from __future__ import annotations

from typing import List, Optional, Annotated

import strawberry
import strawberry_django
from strawberry import auto

from surveys.models import Survey, SurveyMediaAsset, Usage, Price
from .translations import SurveyTranslationType
from .types_category import CategoryType

from app.auth_utils import get_django_user
from user_surveys.models import (
    UserAnswer,
    UserSurvey,
    UserSurveyClassification,
    UserSurveyRecommendation,
)
from surveys.models import Question
from .classification import ClassificationType
from .recommendation import RecommendationType


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
    category: Optional[CategoryType]
    sponsor: auto
    price: auto
    created_at: auto
    updated_at: auto
    sections: List[Annotated["SectionType", strawberry.lazy("surveys.types.content")]]
    translations: List[SurveyTranslationType]

    @strawberry.field
    def collection_id(self) -> Optional[int]:
        collection = self.collections.first()
        return collection.id if collection else None

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
    def user_surveys(self, info) -> List[UserSurveyType]:
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
        user_survey = self.usersurvey_set.filter(user=django_user).exists()
        if not usage:
            return 1 if user_survey else 0
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


@strawberry_django.type(UserSurvey)
class UserSurveyType:
    id: int
    is_paid: auto
    survey_id: auto
    collection_id: auto
    survey: Optional[SurveyType]
    user_id: auto
    child_id: auto
    count_of_ending_options: auto
    evaluated_at: auto
    submitted_at: auto
    score: auto
    last_question_id: auto
    action_id: auto

    @strawberry.field
    def survey_type(self) -> str | None:
        return self.survey.survey_type if self.survey_id and self.survey else None

    @strawberry.field
    def usage_used(self, info) -> int:
        try:
            django_user = get_django_user(info)
        except ValueError:
            return 0
        if django_user.id != self.user_id or not self.survey_id:
            return 0
        usage = Usage.objects.filter(user_id=django_user.id, survey_id=self.survey_id).first()
        return usage.used_count if usage else 0

    @strawberry.field
    def usage_limit(self, info) -> int:
        try:
            django_user = get_django_user(info)
        except ValueError:
            return 1
        if django_user.id != self.user_id or not self.survey_id:
            return 1
        usage = Usage.objects.filter(user_id=django_user.id, survey_id=self.survey_id).first()
        return usage.usage_limit or 1 if usage else 1

    @strawberry.field
    def progress(self, info) -> int:
        try:
            django_user = get_django_user(info)
        except ValueError:
            return 0
        if not self.survey_id or django_user.id != self.user_id:
            return 0
        total = Question.objects.filter(survey_id=self.survey_id, section__isnull=False).count()
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
    survey_id: auto
    user_id: auto
    question_id: auto
    user_survey_id: auto
    answer: auto
    type: auto
    score: auto
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
