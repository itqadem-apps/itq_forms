import base64

import strawberry
import strawberry_django
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ValidationError
from strawberry.types import Info

from app.auth_utils import with_django_user
from user_surveys.models import UserSurvey
from user_surveys.pdf_service import generate_report_pdf
from ..common import RequireAuth
from app.graphql_ids import as_pk


@strawberry.type
class GenerateReportResult:
    pdf_base64: str
    filename: str


@strawberry.type
class GenerateReportMutation:
    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    def generate_report(
        self,
        info: Info,
        user_survey_id: strawberry.ID,
        lang: str = "default",
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> GenerateReportResult:
        user_survey_id = as_pk(user_survey_id)
        user_survey = UserSurvey.objects.filter(id=user_survey_id, user=django_user).first()
        if not user_survey:
            raise ValidationError("Assessment not found.")
        if not user_survey.submitted_at:
            raise ValidationError("Assessment has not been submitted yet.")

        pdf_bytes = generate_report_pdf(user_survey, lang=lang)
        pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")

        filename = f"report_{user_survey.id}.pdf"
        return GenerateReportResult(pdf_base64=pdf_b64, filename=filename)
