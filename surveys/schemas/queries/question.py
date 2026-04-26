import strawberry
from strawberry.types import Info
from django.contrib.auth.base_user import AbstractBaseUser

from app.auth_utils import with_django_user
from surveys.types import QuestionType
from user_surveys.models import UserQuestion, UserSurvey
from ..common import RequireAuth


@strawberry.type
class QuestionQuery:
    @strawberry.field(permission_classes=[RequireAuth])
    @with_django_user
    def question(
        self,
        info: Info,
        user_survey_id: int,
        question_id: int | None = None,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> QuestionType | None:
        user_survey = UserSurvey.objects.filter(id=user_survey_id, user=django_user).first()
        if not user_survey:
            return None

        if user_survey.submitted_at:
            raise ValueError("This assessment is already submitted.")

        qs = UserQuestion.objects.filter(
            user_survey=user_survey,
            section__isnull=False,
        )

        if question_id is not None:
            question = qs.filter(id=question_id).first()
            if question:
                question._user_survey_id = user_survey.id
            return question

        if user_survey.last_question_id:
            ids = list(
                qs.order_by("section__order", "order")
                .values_list("id", flat=True)
            )
            if ids:
                try:
                    idx = ids.index(user_survey.last_question_id)
                    next_id = ids[idx + 1] if idx + 1 < len(ids) else None
                except ValueError:
                    next_id = None
                if next_id is not None:
                    question = UserQuestion.objects.filter(id=next_id).first()
                    if question:
                        question._user_survey_id = user_survey.id
                    return question
            return None

        question = qs.order_by("section__order", "order").first()
        if question:
            question._user_survey_id = user_survey.id
        return question
