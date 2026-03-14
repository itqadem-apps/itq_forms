from __future__ import annotations

from typing import List, Optional, Annotated

import strawberry
import strawberry_django
from strawberry import auto
from strawberry.types import Info

from surveys.models import Survey, Usage, Price
from .translations import SurveyTranslationType
from .types_category import CategoryType

from app.auth_utils import get_django_user
from user_surveys.models import UserSurvey


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

    @strawberry.field
    def time_limit(self) -> Optional[str]:
        value = getattr(self, "time_limit", None)
        if value is None:
            return None
        return str(value)
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
    cover_id: auto
    thumb_id: auto
    created_at: auto
    updated_at: auto
    sections: List[Annotated["SectionType", strawberry.lazy("surveys.types.content")]]
    translations: List[SurveyTranslationType]

    @strawberry.field
    def collection_id(self) -> Optional[int]:
        collection = self.collections.first()
        return collection.id if collection else None

    @strawberry.field
    def status(self) -> str | None:
        return self.status.status if self.status_id else None

    @strawberry.field
    def user_surveys(self, info: Info) -> List[Annotated["UserSurveyType", strawberry.lazy("user_surveys.types.user_survey")]]:
        try:
            django_user = get_django_user(info)
            return list(self.usersurvey_set.filter(user=django_user, submitted_at__isnull=True))
        except ValueError:
            return []

    @strawberry.field
    def is_enrolled(self, info: Info) -> bool:
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
    def usage_used(self, info: Info) -> int:
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
    def usage_limit(self, info: Info) -> int:
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


@strawberry.type
class SurveyPayload:
    success: bool
    message: Optional[str]
    survey: Optional[SurveyType]


@strawberry_django.type(Price)
class PriceType:
    id: auto
    survey_id: auto
    currency: auto
    amount_cents: auto
    compare_at_amount_cents: auto
