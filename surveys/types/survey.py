from __future__ import annotations

from typing import List, Optional, Annotated

import strawberry
import strawberry_django
from strawberry import auto
from strawberry.types import Info

from surveys.models import Survey, Usage
from .translations import SurveyTranslationType
from .types_category import CategoryType
from survey_collections.types.collection import SurveyCollectionType

from app.auth_utils import get_django_user
from surveys.usage_access import (
    resolve_usage_limit,
    resolve_usage_used,
)
from user_surveys.models import UserSurvey


@strawberry_django.type(Survey)
class SurveyType:
    id: auto
    status: auto
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
    enable_anti_cheat: auto
    lock_answers: auto
    randomize_questions: auto
    randomize_options: auto
    category_id: auto
    category: Optional[CategoryType]
    sponsor: auto
    cover_id: auto
    thumb_id: auto
    created_at: auto
    updated_at: auto
    sections: List[Annotated["SectionType", strawberry.lazy("surveys.types.content")]]
    translations: List[SurveyTranslationType]
    classifications: List[Annotated["ClassificationType", strawberry.lazy("classifications.types.classification")]]
    recommendations: List[Annotated["RecommendationType", strawberry.lazy("recommendations.types.recommendation")]]
    actions: List[Annotated["ActionType", strawberry.lazy("recommendations.types.action")]]

    @strawberry.field
    def classifications(self) -> List[ClassificationType]:
        return list(self.classifications.filter(deleted_at__isnull=True))

    @strawberry.field
    def sections(self) -> List[Annotated["SectionType", strawberry.lazy("surveys.types.content")]]:
        return list(self.sections.filter(deleted_at__isnull=True))

    @strawberry.field
    def collection_id(self) -> Optional[int]:
        collection = self.collections.first()
        return collection.id if collection else None

    @strawberry.field
    def collection(self) -> Optional[SurveyCollectionType]:
        return self.collections.first()

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

        # No child scope here: the survey card has no child context, so it
        # reports every attempt the user has spent on this survey.
        return resolve_usage_used(user_id=django_user.id, survey_id=self.id)

    @strawberry.field
    def usage_limit(self, info: Info) -> Optional[int]:
        """``null`` means the grant is uncapped — see
        :meth:`UserSurveyType.usage_limit`."""
        try:
            django_user = get_django_user(info)
        except ValueError:
            return 0

        return resolve_usage_limit(user_id=django_user.id, survey_id=self.id)

    @strawberry.field
    def prices(self) -> List["PriceType"]:
        return list(self.prices.all())


@strawberry.type
class SurveyPayload:
    success: bool
    message: Optional[str]
    survey: Optional[SurveyType]


from pricing.types import PriceType  # noqa: E402 — re-export for backward compat
