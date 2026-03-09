import strawberry
import strawberry_django
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from strawberry import UNSET

from app.auth_utils import with_django_user
from app.permissions import check_permission
from surveys.inputs import SurveyCreateInput, SurveyUpdateInput
from surveys.types import SurveyType
from surveys.types.survey import SurveyPayload
from surveys.models import (
    Survey,
    SurveyTranslation,
    SectionTranslation,
    Question,
    QuestionTranslation,
    AnswerSchemaOption,
    AnswerSchemaOptionTranslation,
    Classification,
    ClassificationTranslation,
    Recommendation,
    RecommendationTranslation,
    Action,
    ActionTranslation,
)
from taxonomy.models import Category
from ..common import RequireAuth, OperationResult
from ..utils import input_to_dict, clone_instance


def _type_from_input(info, input, **kw):
    return input.survey_type or 'survey'


def _type_from_survey_id(info, id, **kw):
    return Survey.objects.values_list('survey_type', flat=True).get(pk=id)


def _type_from_update_input(info, input, **kw):
    return Survey.objects.values_list('survey_type', flat=True).get(pk=input.id)


@strawberry.type
class SurveyMutations:
    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_input, 'create')
    @transaction.atomic
    def create_survey(
        self,
        info,
        input: SurveyCreateInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SurveyPayload:
        data = input_to_dict(input, exclude=['category_id', 'translations'])

        if input.category_id is not UNSET and input.category_id is not None:
            try:
                data['category'] = Category.objects.get(category_id=input.category_id)
            except Category.DoesNotExist:
                raise ObjectDoesNotExist(f"Category not found: {input.category_id}")

        survey = Survey.objects.create(**data)

        if input.translations is not UNSET and input.translations:
            for t in input.translations:
                SurveyTranslation.objects.create(survey=survey, **input_to_dict(t))

        return SurveyPayload(success=True, message=None, survey=survey)

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_update_input, 'update')
    @transaction.atomic
    def update_survey(
        self,
        info,
        input: SurveyUpdateInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SurveyPayload:
        survey = Survey.objects.get(pk=input.id)

        data = input_to_dict(input, exclude=['id', 'category_id', 'translations'])
        for field, value in data.items():
            setattr(survey, field, value)

        if input.category_id is not UNSET:
            if input.category_id:
                try:
                    survey.category = Category.objects.get(category_id=input.category_id)
                except Category.DoesNotExist:
                    raise ObjectDoesNotExist(f"Category not found: {input.category_id}")
            else:
                survey.category = None

        survey.save()

        if input.translations is not UNSET and input.translations:
            for t in input.translations:
                t_data = input_to_dict(t, exclude=['id'])
                language = t_data.pop('language', None)
                if language:
                    SurveyTranslation.objects.update_or_create(
                        survey=survey, language=language, defaults=t_data
                    )

        return SurveyPayload(success=True, message=None, survey=survey)

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_survey_id, 'delete')
    def delete_survey(
        self,
        info,
        id: int,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> OperationResult:
        Survey.objects.get(pk=id).delete()
        return OperationResult(success=True)

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_survey_id, 'create')
    @transaction.atomic
    def duplicate_survey(
        self,
        info,
        id: int,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SurveyPayload:
        original = Survey.objects.get(pk=id)

        new_survey = clone_instance(
            original,
            title=f"{original.title} (Copy)",
            slug=f"{original.slug}-copy" if original.slug else None,
        )

        # Duplicate survey translations
        for t in original.translations.all():
            clone_instance(
                t,
                survey=new_survey,
                title=f"{t.title} (Copy)" if t.title else None,
                slug=f"{t.slug}-copy" if t.slug else None,
            )

        # Duplicate sections → questions → schemas → options (with all translations)
        for section in original.sections.all():
            new_section = clone_instance(section, survey=new_survey)

            for t in SectionTranslation.objects.filter(section=section):
                clone_instance(t, section=new_section)

            for question in Question.objects.filter(section=section):
                new_question = clone_instance(question, survey=new_survey, section=new_section)

                for t in QuestionTranslation.objects.filter(question=question):
                    clone_instance(t, question=new_question)

                if hasattr(question, 'answer_schema'):
                    old_schema = question.answer_schema
                    new_schema = clone_instance(
                        old_schema,
                        survey=new_survey,
                        section=new_section,
                        question=new_question,
                    )
                    for option in AnswerSchemaOption.objects.filter(schema=old_schema):
                        new_option = clone_instance(
                            option,
                            survey=new_survey,
                            section=new_section,
                            question=new_question,
                            schema=new_schema,
                        )
                        for t in AnswerSchemaOptionTranslation.objects.filter(option=option):
                            clone_instance(t, option=new_option)

        # Duplicate classifications
        for classification in original.classifications.all():
            new_classification = clone_instance(classification, survey=new_survey)
            for t in ClassificationTranslation.objects.filter(classification=classification):
                clone_instance(t, classification=new_classification)

        # Duplicate recommendations
        for recommendation in original.recommendations.all():
            new_recommendation = clone_instance(recommendation, survey=new_survey)
            for t in RecommendationTranslation.objects.filter(recommendation=recommendation):
                clone_instance(t, recommendation=new_recommendation)

        # Duplicate actions
        for action in original.actions.all():
            new_action = clone_instance(action, survey=new_survey)
            for t in ActionTranslation.objects.filter(action=action):
                clone_instance(t, action=new_action)

        return SurveyPayload(success=True, message=None, survey=new_survey)

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_survey_id, 'update')
    def update_survey_status(
        self,
        info,
        id: int,
        status: str,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SurveyType:
        survey = Survey.objects.get(pk=id)
        survey.update_status(status, django_user)
        return survey
