import strawberry
from django.contrib.auth.base_user import AbstractBaseUser
from pkg_filters.integrations.django import DjangoQueryContext

from app.auth_utils import with_django_user
from surveys.filters import QuestionProjection, QuestionSpec, questions_pipeline
from surveys.inputs import QuestionsFilters, QuestionsFiltersInput
from surveys.models import Question
from surveys.types import QuestionsFiltersGQL, QuestionsResultsGQL
from user_surveys.models import UserAnswer, UserSurvey
from ..common import RequireAuth


@strawberry.type
class QuestionsQuery:
    @strawberry.field(permission_classes=[RequireAuth])
    @with_django_user
    def questions(
        self,
        info,
        user_survey_id: int,
        limit: int = 20,
        offset: int = 0,
        filters: QuestionsFiltersInput | None = None,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> QuestionsResultsGQL:
        user_survey = UserSurvey.objects.filter(
            id=user_survey_id,
            user=django_user,
        ).first()
        if not user_survey:
            raise ValueError("Assessment not found.")

        qs = Question.objects.filter(
            survey_id=user_survey.survey_id,
            section__isnull=False,
        )
        filters_input = filters or QuestionsFiltersInput()
        if filters_input.question_ids:
            qs = qs.filter(id__in=filters_input.question_ids)

        spec = QuestionSpec(
            limit=limit,
            offset=offset,
            projection=QuestionProjection(),
            filters=QuestionsFilters(
                question_ids=filters_input.question_ids,
                section_id=filters_input.section_id,
                is_required=filters_input.is_required,
                question_type=filters_input.question_type,
                answered=filters_input.answered,
            ),
            sort=None,
        )
        base_qs = questions_pipeline.run(DjangoQueryContext(qs, spec)).stmt

        if filters_input.answered is not None:
            answered_ids = set(
                UserAnswer.objects.filter(user_survey=user_survey)
                .exclude(answer__isnull=True, selected_options__isnull=True)
                .values_list("question_id", flat=True)
            )
            if filters_input.answered:
                base_qs = base_qs.filter(id__in=answered_ids)
            else:
                base_qs = base_qs.exclude(id__in=answered_ids)

        total = base_qs.count()
        questions = list(base_qs.order_by("section__order", "order")[offset : offset + limit])
        for question in questions:
            question._user_survey_id = user_survey.id
        filters_out = QuestionsFiltersGQL(
            question_ids=filters_input.question_ids,
            section_id=filters_input.section_id,
            is_required=filters_input.is_required,
            question_type=filters_input.question_type,
            answered=filters_input.answered,
        )
        return QuestionsResultsGQL(items=questions, total=total, filters=filters_out)
