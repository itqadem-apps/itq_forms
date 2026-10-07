from typing import Optional

import strawberry
from strawberry.types import Info
from django.contrib.auth.base_user import AbstractBaseUser

from app.auth_utils import with_django_user
from user_surveys.models import UserSurvey
from user_surveys.services import AlreadySubmitted, check_time_expired,finish_assessment as finish_assessment_service
from user_surveys.types import EndReason, stored_end_reason, threshold_reached
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
    ) -> Optional[EndReason]:
        """Why the attempt ended, from `forms:AD-6`'s enum, or null while it is open. Null is falsy
        and a reason truthy, so a client reading the old Boolean keeps working."""
        user_survey_id = as_pk(user_survey_id)
        user_survey = UserSurvey.objects.filter(id=user_survey_id, user=django_user).first()
        if not user_survey:
            return None
        if user_survey.submitted_at:
            return stored_end_reason(user_survey) or EndReason.FALLTHROUGH_COMPLETE

        try:
            # time-based termination (auto-submits)
            if check_time_expired(user_survey):
                finish_assessment_service(user_survey, reason=UserSurvey.TERMINATION_TIME_EXPIRED)
                return EndReason.FORCE_TERMINATED

            # ending-option-based termination (auto-submits)
            if threshold_reached(user_survey):
                finish_assessment_service(user_survey, reason=UserSurvey.TERMINATION_ENDING_OPTION)
                return EndReason.ENDING_THRESHOLD
        except AlreadySubmitted:
            # An overlapping request finished it first; report the reason that one stored.
            user_survey.refresh_from_db()
            return stored_end_reason(user_survey) or EndReason.FALLTHROUGH_COMPLETE

        return None
