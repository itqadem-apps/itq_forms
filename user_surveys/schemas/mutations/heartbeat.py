import strawberry
import strawberry_django
from strawberry.types import Info
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.utils.timezone import now

from app.auth_utils import with_django_user
from user_surveys.models import UserSurvey
from ..common import RequireAuth


@strawberry.type
class HeartbeatMutation:
    @strawberry_django.mutation(permission_classes=[RequireAuth])
    @with_django_user
    def heartbeat(
        self,
        info: Info,
        user_survey_id: int,
        session_token: str,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> bool:
        user_survey = UserSurvey.objects.filter(id=user_survey_id, user=django_user).first()
        if not user_survey:
            raise ValidationError("Assessment not found.")
        if user_survey.submitted_at:
            raise ValidationError("This assessment is already submitted.")
        if not user_survey.enable_anti_cheat:
            return True
        if str(user_survey.session_token) != session_token:
            raise ValidationError("Session conflict detected. This assessment is open in another window.")
        return True
