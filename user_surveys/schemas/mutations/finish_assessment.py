import strawberry
import strawberry_django
from strawberry.types import Info
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.db import transaction

from app.auth_utils import with_django_user
from surveys.models import Usage
from surveys.usage_access import select_usage_to_consume
from user_surveys.types import FinishAssessmentResult
from user_surveys.models import UserSurvey
from user_surveys.services import finish_assessment as finish_assessment_service
from ..common import RequireAuth


@strawberry.type
class FinishAssessmentMutation:
    @strawberry_django.mutation(permission_classes=[RequireAuth])
    @with_django_user
    def finish_assessment(
        self,
        info: Info,
        user_survey_id: int,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> FinishAssessmentResult:
        user_survey = UserSurvey.objects.filter(id=user_survey_id, user=django_user).first()
        if not user_survey:
            raise ValidationError("Assessment not found.")
        if user_survey.submitted_at:
            raise ValidationError("This assessment is already submitted.")

        with transaction.atomic():
            finish_assessment_service(user_survey)
            usages = list(
                Usage.objects.select_for_update()
                .filter(user=django_user, survey=user_survey.survey)
                .order_by("created_at", "id")
            )
            usage = select_usage_to_consume(usages)
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
