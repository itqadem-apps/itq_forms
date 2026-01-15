from dataclasses import fields as dc_fields
from typing import List

import strawberry
import strawberry_django
from django.db import transaction
from django.db.models import Count
from django.contrib.auth.base_user import AbstractBaseUser
from pkg_filters.integrations.django import DjangoQueryContext
from pkg_filters.integrations.strawberry import has_any_under_prefix, get_root_field_paths
from strawberry_django.optimizer import DjangoOptimizerExtension

from app.auth import strawberry_auth
from .filters import (
    pipeline,
    survey_sort_input_to_spec,
    SurveyProjection,
    SurveySpec,
    QuestionProjection,
    QuestionSpec,
    questions_pipeline,
)
from .inputs import (
    SurveyFilters,
    SurveyFiltersInput,
    SurveysListInput,
    QuestionsFiltersInput,
    QuestionsFilters,
)
from .models import AnswerSchemaOption, Question, Survey
from .types import (
    FacetGQL,
    FacetValueGQL,
    SurveyResultsGQL,
    SurveyType,
    UserAssessmentType,
    QuestionType,
    UserAnswerType,
    FinishAssessmentResult,
    UserAssessmentClassificationType,
    UserAssessmentRecommendationType,
    QuestionsResultsGQL,
    QuestionsFiltersGQL,
)
from user_surveys.models import UserAnswer, UserAssessment
from user_surveys.services import enroll_user_in_assessment, finish_assessment as finish_assessment_service
from app.auth_utils import with_django_user
from strawberry.types import Info

RequireAuth = strawberry_auth.require_authenticated()


@strawberry.type
class Query:
    @strawberry.field()
    def surveys(
            self,
            info,
            surveys_list_input: SurveysListInput,
    ) -> SurveyResultsGQL:
        paths = get_root_field_paths(info, "surveys")
        qs = Survey.objects.all()
        if has_any_under_prefix(paths, ("items", "contentType")):
            qs = qs.select_related("content_type")
        # Prefetching is delegated to strawberry_django optimizer to avoid
        # conflicting lookups when it applies its own Prefetch querysets.

        filters_input: SurveyFiltersInput | None = surveys_list_input.filters
        filters_data = {}
        for field in dc_fields(SurveyFilters):
            name = field.name
            if name in {"created_at", "updated_at"}:
                value = getattr(filters_input, name, None) if filters_input else None
                filters_data[name] = value.to_vo() if value else None
                continue
            filters_data[name] = getattr(filters_input, name, None) if filters_input else None

        spec = SurveySpec(
            limit=surveys_list_input.limit,
            offset=surveys_list_input.offset,
            projection=SurveyProjection(),
            filters=SurveyFilters(**filters_data),
            sort=survey_sort_input_to_spec(surveys_list_input.sort),
        )
        base_qs = pipeline.run(DjangoQueryContext(qs, spec)).stmt

        total = base_qs.count()
        items = base_qs[surveys_list_input.offset: surveys_list_input.offset + surveys_list_input.limit]

        facets: List[FacetGQL] = []
        if has_any_under_prefix(paths, ("facets",)):
            status_values = [
                FacetValueGQL(value=row["status__status"], count=row["count"])
                for row in base_qs.values("status__status")
                .annotate(count=Count("id"))
                .order_by("status__status")
            ]
            facets.append(FacetGQL(name="status", values=status_values))

            assessment_type_values = [
                FacetValueGQL(value=row["assessment_type"], count=row["count"])
                for row in base_qs.values("assessment_type")
                .annotate(count=Count("id"))
                .order_by("assessment_type")
            ]
            facets.append(FacetGQL(name="assessment_type", values=assessment_type_values))

            language_values = [
                FacetValueGQL(value=row["language"], count=row["count"])
                for row in base_qs.values("language").annotate(count=Count("id")).order_by("language")
            ]
            facets.append(FacetGQL(name="language", values=language_values))

        return SurveyResultsGQL(items=items, total=total, facets=facets)

    @strawberry.field()
    def survey(self, info: Info, id: int) -> SurveyType | None:
        try:
            return Survey.objects.get(pk=id)
        except Survey.DoesNotExist:
            return None

    @strawberry.field(permission_classes=[RequireAuth])
    @with_django_user
    def user_assessments(
        self,
        info: Info,
        limit: int = 20,
        offset: int = 0,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> list[UserAssessmentType]:
        qs = UserAssessment.objects.filter(user=django_user).order_by("-submitted_at")
        return list(qs[offset : offset + limit])

    @strawberry.field(permission_classes=[RequireAuth])
    @with_django_user
    def question(
        self,
        info: Info,
        user_assessment_id: int,
        question_id: int | None = None,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> QuestionType | None:
        
        user_assessment = UserAssessment.objects.filter(id=user_assessment_id, user=django_user).first()
        if not user_assessment:
            return None

        if user_assessment.submitted_at:
            raise ValueError("This assessment is already submitted.")

        survey = user_assessment.survey
        if not survey:
            return None

        if question_id is not None:
            question = (
                survey.questions.exclude(section__isnull=True)
                .filter(id=question_id)
                .first()
            )
            if question:
                question._user_assessment_id = user_assessment.id
            return question

        if user_assessment.last_question_id:
            ids = list(
                survey.questions.exclude(section__isnull=True)
                .order_by("section__order", "order")
                .values_list("id", flat=True)
            )
            if ids:
                try:
                    idx = ids.index(user_assessment.last_question_id)
                    next_id = ids[idx + 1] if idx + 1 < len(ids) else None
                except ValueError:
                    next_id = None
                if next_id is not None:
                    question = survey.questions.filter(id=next_id).first()
                    if question:
                        question._user_assessment_id = user_assessment.id
                    return question
            return None

        question = (
            survey.questions.exclude(section__isnull=True)
            .order_by("section__order", "order")
            .first()
        )
        if question:
            question._user_assessment_id = user_assessment.id
        return question

    @strawberry.field(permission_classes=[RequireAuth])
    @with_django_user
    def questions(
        self,
        info: Info,
        user_assessment_id: int,
        limit: int = 20,
        offset: int = 0,
        filters: QuestionsFiltersInput | None = None,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> QuestionsResultsGQL:
        user_assessment = UserAssessment.objects.filter(
            id=user_assessment_id,
            user=django_user,
        ).first()
        if not user_assessment:
            raise ValueError("Assessment not found.")

        qs = Question.objects.filter(
            survey_id=user_assessment.survey_id,
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
                UserAnswer.objects.filter(user_assessment=user_assessment)
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
            question._user_assessment_id = user_assessment.id
        filters_out = QuestionsFiltersGQL(
            question_ids=filters_input.question_ids,
            section_id=filters_input.section_id,
            is_required=filters_input.is_required,
            question_type=filters_input.question_type,
            answered=filters_input.answered,
        )
        return QuestionsResultsGQL(items=questions, total=total, filters=filters_out)


@strawberry.type
class Mutation:
    @strawberry.mutation(permission_classes=[RequireAuth])
    @with_django_user
    def enroll_assessment(
        self,
        info: Info,
        survey_id: int,
        child_id: str | None = None,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> UserAssessmentType:
        try:
            survey = Survey.objects.get(pk=survey_id)
        except Survey.DoesNotExist:
            raise ValueError(f"Survey not found: {survey_id}")

        user_assessment, _created = enroll_user_in_assessment(
            request_user=django_user,
            survey_id=survey.id,
            child_id=child_id,
        )
        return user_assessment

    @strawberry.mutation(permission_classes=[RequireAuth])
    @with_django_user
    def answer_question(
        self,
        info: Info,
        user_assessment_id: int,
        question_id: int,
        answer: list[str],
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> UserAnswerType:
        with transaction.atomic():
            user_assessment = UserAssessment.objects.filter(id=user_assessment_id, user=django_user).first()
            if not user_assessment:
                raise ValueError("Assessment not found.")
            if user_assessment.submitted_at:
                raise ValueError("This assessment is already submitted.")

            question = Question.objects.filter(id=question_id, survey_id=user_assessment.survey_id).first()
            if not question:
                raise ValueError("Question not found.")

            user_answer, _created = UserAnswer.objects.get_or_create(
                user_assessment=user_assessment,
                question_id=question.id,
                defaults={
                    "user": django_user,
                    "survey_id": user_assessment.survey_id,
                    "type": question.type,
                    "order": question.order,
                },
            )

            def parse_ids(values: list[str]) -> list[int]:
                ids: list[int] = []
                for raw in values:
                    try:
                        ids.append(int(raw))
                    except (TypeError, ValueError):
                        continue
                return ids

            def require_schema():
                if not hasattr(question, "answer_schema"):
                    raise ValueError("Answer schema not found.")

            def require_options(option_ids: list[int]) -> list[AnswerSchemaOption]:
                if not option_ids:
                    raise ValueError("No options provided.")
                options = list(question.answer_schema.options.filter(id__in=option_ids))
                if len(options) != len(set(option_ids)):
                    raise ValueError("One or more option IDs are invalid.")
                return options

            if question.type == Question.QUESTION_TYPE_CHECKBOX_MCQ:
                require_schema()
                option_ids = parse_ids(answer)
                options = require_options(option_ids)
                ending_count = sum(1 for opt in options if opt.ending_option)
                if ending_count:
                    user_assessment.count_of_ending_options += ending_count
                elif user_assessment.survey and user_assessment.survey.end_based_on_answer_repeat_in_row:
                    user_assessment.count_of_ending_options = 0
                user_answer.selected_options.set(options)
                user_answer.answer = ", ".join([opt.text for opt in options if opt.text])
            elif question.type in [Question.QUESTION_TYPE_RADIO_MCQ, Question.QUESTION_TYPE_DROPDOWN_MCQ]:
                require_schema()
                option_ids = parse_ids(answer)
                options = require_options(option_ids)
                option = options[0]
                if option.ending_option:
                    user_assessment.count_of_ending_options += 1
                elif user_assessment.survey and user_assessment.survey.end_based_on_answer_repeat_in_row:
                    user_assessment.count_of_ending_options = 0
                user_answer.selected_options.set([option])
                user_answer.answer = option.text
            elif question.type in [
                Question.QUESTION_TYPE_TEXT,
                Question.QUESTION_TYPE_TEXTAREA,
                Question.QUESTION_TYPE_DATE,
                Question.QUESTION_TYPE_TIME,
                Question.QUESTION_TYPE_DATETIME,
                Question.QUESTION_TYPE_NUMBER,
                Question.QUESTION_TYPE_FILE,
            ]:
                user_answer.selected_options.clear()
                user_answer.answer = answer[0] if answer else ""
            elif question.type in [Question.QUESTION_TYPE_RADIO_GRID, Question.QUESTION_TYPE_CHECKBOX_GRID]:
                require_schema()
                flat_ids: list[str] = []
                for token in answer:
                    flat_ids.extend(token.split("-"))
                option_ids = parse_ids(flat_ids)
                options = require_options(option_ids)
                user_answer.selected_options.set(options)
                user_answer.answer = ",".join(answer)
            else:
                raise ValueError("Unsupported question type.")

            user_assessment.last_question_id = question.id
            user_assessment.save(update_fields=["last_question", "count_of_ending_options"])
            user_answer.save()
            return user_answer

    @strawberry.mutation(permission_classes=[RequireAuth])
    @with_django_user
    def finish_assessment(
        self,
        info: Info,
        user_assessment_id: int,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> FinishAssessmentResult:
        user_assessment = UserAssessment.objects.filter(id=user_assessment_id, user=django_user).first()
        if not user_assessment:
            raise ValueError("Assessment not found.")
        if user_assessment.submitted_at:
            raise ValueError("This assessment is already submitted.")

        with transaction.atomic():
            finish_assessment_service(user_assessment)

        user_assessment.refresh_from_db()
        classifications = list(user_assessment.userassessmentclassification_set.all())
        recommendations = list(user_assessment.userassessmentrecommendation_set.all())

        evaluated_at = user_assessment.evaluated_at.isoformat() if user_assessment.evaluated_at else None
        return FinishAssessmentResult(
            status="finished",
            score=user_assessment.score,
            evaluated_at=evaluated_at,
            classifications=classifications,
            recommendations=recommendations,
        )

    @strawberry.field(permission_classes=[RequireAuth])
    def me(self, info: Info) -> str:
        return info.context.user.identity.preferred_username



schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    extensions=[
        DjangoOptimizerExtension,
    ],
)
