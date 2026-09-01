import strawberry
import strawberry_django
from strawberry.types import Info
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.db.models import F

from app.auth_utils import with_django_user
from user_surveys.models import UserSurvey, TabSwitchEvent
from ..common import RequireAuth
from app.graphql_ids import as_pk


@strawberry.type
class ReportTabSwitchMutation:
    @strawberry_django.mutation(permission_classes=[RequireAuth])
    @with_django_user
    def report_tab_switch(
        self,
        info: Info,
        user_survey_id: strawberry.ID,
        event_type: str,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> bool:
        user_survey_id = as_pk(user_survey_id)
        user_survey = UserSurvey.objects.filter(id=user_survey_id, user=django_user).first()
        if not user_survey:
            raise ValidationError("Assessment not found.")
        if user_survey.submitted_at:
            return False
        if not user_survey.enable_anti_cheat:
            return False

        TabSwitchEvent.objects.create(
            user_survey=user_survey,
            event_type=event_type,
        )
        UserSurvey.objects.filter(id=user_survey.id).update(
            tab_switch_count=F("tab_switch_count") + 1,
        )
        return True
