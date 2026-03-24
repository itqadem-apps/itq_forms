import strawberry
import strawberry_django
from strawberry.types import Info
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ValidationError

from app.auth_utils import with_django_user
from interface.grpc.children_client import ChildrenClient
from surveys.models import Survey, Usage
from user_surveys.types import UserSurveyType
from accounts.models import Child
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
            with ChildrenClient() as client:
                response = client.get_children_by_guardian(guardian_user_id=str(django_user.id), status="active")
            grpc_child = next((c for c in response.items if c.id == str(child_id)), None)
            if not grpc_child:
                raise ValidationError("Invalid child_id for this user.")
            child, _ = Child.objects.update_or_create(
                id=grpc_child.id,
                defaults={"name": grpc_child.name, "photo_id": grpc_child.photo_id or None},
            )

        is_free = not survey.prices.filter(amount_cents__gt=0).exists()
        if not is_free:
            usage = Usage.objects.filter(user=django_user, survey=survey).first()
            if usage:
                if usage.usage_limit and usage.used_count >= usage.usage_limit:
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
