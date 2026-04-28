import strawberry
import strawberry_django
from strawberry.types import Info
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ValidationError

from app.auth_utils import with_django_user
from surveys.models import Survey, Usage
from surveys.usage_access import summarize_usage_rows
from user_surveys.child_projection import get_active_child_for_user
from user_surveys.types import UserSurveyType
from user_surveys.models import UserSurvey
from user_surveys.services import enroll_user_in_assessment
from ..common import RequireAuth


@strawberry.type
class EnrollAssessmentMutation:
    @strawberry_django.mutation(permission_classes=[RequireAuth])
    @with_django_user
    def enroll_assessment(
        self,
        info: Info,
        survey_id: int,
        child_id: str | None = None,
        collection_id: int | None = None,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> UserSurveyType:
        survey = Survey.objects.get(pk=survey_id)

        child = None
        if child_id:
            child = get_active_child_for_user(str(django_user.id), str(child_id))
            if child is None:
                raise ValidationError("Invalid child_id for this user.")

        is_free = not survey.prices.filter(amount_cents__gt=0).exists()
        if not is_free:
            usages = list(Usage.objects.filter(user=django_user, survey=survey).order_by("created_at", "id"))
            summary = summarize_usage_rows(usages)
            if summary.has_any:
                if not summary.has_unlimited and summary.total_used >= summary.total_limit:
                    raise ValidationError("Usage limit reached for this survey.")
            elif UserSurvey.objects.filter(user=django_user, survey=survey).exists():
                raise ValidationError("Usage limit reached. You are already enrolled in this survey.")

        user_survey, _created = enroll_user_in_assessment(
            request_user=django_user,
            survey_id=survey.id,
            child=child,
            collection_id=collection_id,
        )
        return user_survey
