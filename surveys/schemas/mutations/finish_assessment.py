import strawberry
from django.contrib.auth.base_user import AbstractBaseUser
from django.db import transaction

from app.auth_utils import with_django_user
from surveys.models import Usage
from surveys.types import FinishAssessmentResult
from user_surveys.models import UserSurvey
from user_surveys.services import finish_assessment as finish_assessment_service
from ..common import RequireAuth


@strawberry.type
class FinishAssessmentMutation:
    @strawberry.mutation(permission_classes=[RequireAuth])
    @with_django_user
    def finish_assessment(
        self,
        info,
        user_survey_id: int,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> FinishAssessmentResult:
        user_survey = UserSurvey.objects.filter(id=user_survey_id, user=django_user).first()
        if not user_survey:
            raise ValueError("Assessment not found.")
        if user_survey.submitted_at:
            raise ValueError("This assessment is already submitted.")

        with transaction.atomic():
            finish_assessment_service(user_survey)
            usage = (
                Usage.objects.select_for_update()
                .filter(user=django_user, survey=user_survey.survey)
                .first()
            )
            if usage:
                usage.used_count += 1
                usage.save(update_fields=["used_count"])

        user_survey.refresh_from_db()
        classifications = list(user_survey.usersurveyclassification_set.all())
        recommendations = list(user_survey.usersurveyrecommendation_set.all())

        evaluated_at = user_survey.evaluated_at.isoformat() if user_survey.evaluated_at else None
        return FinishAssessmentResult(
            status="finished",
            score=user_survey.score,
            evaluated_at=evaluated_at,
            classifications=classifications,
            recommendations=recommendations,
        )
