import strawberry
from django.contrib.auth.base_user import AbstractBaseUser

from app.auth_utils import with_django_user
from interface.grpc.children_client import ChildrenClient
from surveys.models import Survey, Usage
from surveys.types import UserSurveyType
from user_surveys.models import UserSurvey
from user_surveys.services import enroll_user_in_assessment
from ..common import RequireAuth


@strawberry.type
class EnrollAssessmentMutation:
    @strawberry.mutation(permission_classes=[RequireAuth])
    @with_django_user
    def enroll_assessment(
        self,
        info,
        survey_id: int,
        child_id: str | None = None,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> UserSurveyType:
        try:
            survey = Survey.objects.get(pk=survey_id)
        except Survey.DoesNotExist:
            raise ValueError(f"Survey not found: {survey_id}")

        if child_id:
            with ChildrenClient() as client:
                response = client.get_children_by_guardian(guardian_user_id=str(django_user.id), status="active")
            if not any(child.id == str(child_id) for child in response.items):
                raise ValueError("Invalid child_id for this user.")

        usage = Usage.objects.filter(user=django_user, survey=survey).first()
        if usage:
            if usage.usage_limit and usage.used_count >= usage.usage_limit:
                raise ValueError("Usage limit reached for this survey.")
        elif UserSurvey.objects.filter(user=django_user, survey=survey).exists():
            raise ValueError("Usage limit reached. You are already enrolled in this survey.")

        user_survey, _created = enroll_user_in_assessment(
            request_user=django_user,
            survey_id=survey.id,
            child_id=child_id,
        )
        return user_survey
