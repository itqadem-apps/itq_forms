import strawberry
from strawberry.types import Info
from django.contrib.auth.base_user import AbstractBaseUser

from app.auth_utils import with_django_user
from user_surveys.models import UserSurvey
from user_surveys.services import check_time_expired, finish_assessment as finish_assessment_service
from ..common import RequireAuth
from app.graphql_ids import as_pk


@strawberry.type
class ShouldTerminateQuery:
    @strawberry.field(permission_classes=[RequireAuth])
    @with_django_user
    def should_terminate(
        self,
        info: Info,
        user_survey_id: strawberry.ID,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> bool:
        user_survey_id = as_pk(user_survey_id)
        user_survey = UserSurvey.objects.filter(id=user_survey_id, user=django_user).first()
        if not user_survey:
            return False
        if user_survey.submitted_at:
            return True

        # time-based termination (auto-submits)
        if check_time_expired(user_survey):
            finish_assessment_service(user_survey, reason=UserSurvey.TERMINATION_TIME_EXPIRED)
            return True

        # ending-option-based termination (auto-submits)
        if (
            user_survey.allow_end_based_on_answer_repeat
            and user_survey.answers_count_to_end > 0
            and user_survey.count_of_ending_options >= user_survey.answers_count_to_end
        ):
            finish_assessment_service(user_survey, reason=UserSurvey.TERMINATION_ENDING_OPTION)
            return True

        return False
