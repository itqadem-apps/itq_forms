import strawberry
import strawberry_django
from strawberry.types import Info
from django.contrib.auth.base_user import AbstractBaseUser
from django.utils.timezone import now
from typing import List

from app.auth_utils import with_django_user
from app.permissions import check_permission
from surveys.inputs import ClassificationInput, RecommendationInput, ActionInput
from surveys.types import ClassificationType, RecommendationType, ActionType
from surveys.models import (
    Survey,
    Classification,
    ClassificationTranslation,
    Recommendation,
    RecommendationTranslation,
    Action,
    ActionTranslation,
    AnswerSchemaOption,
)
from ..common import RequireAuth, OperationResult
from ..utils import input_to_dict


def _type_from_survey_id(info, survey_id, **kw):
    return Survey.objects.values_list('survey_type', flat=True).get(pk=survey_id)


def _type_from_classification_id(info, id, **kw):
    return Classification.objects.select_related('survey').get(pk=id).survey.survey_type


def _type_from_recommendation_id(info, id, **kw):
    return Recommendation.objects.select_related('survey').get(pk=id).survey.survey_type


def _type_from_action_id(info, id, **kw):
    return Action.objects.select_related('survey').get(pk=id).survey.survey_type


@strawberry.type
class EvaluationMutations:
    # ==================== Classification Mutations ====================

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_survey_id, 'update')
    def create_classification(
        self,
        info: Info,
        survey_id: int,
        input: ClassificationInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> ClassificationType:
        """Create a new classification for a survey"""
        survey = Survey.objects.get(pk=survey_id)

        data = input_to_dict(input, exclude=['translations'])
        data['survey'] = survey

        classification = Classification.objects.create(**data)

        if input.translations:
            for trans_input in input.translations:
                ClassificationTranslation.objects.create(
                    classification=classification,
                    language=trans_input.language,
                    name=trans_input.name,
                )

        return classification

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_classification_id, 'update')
    def update_classification(
        self,
        info: Info,
        id: int,
        input: ClassificationInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> ClassificationType:
        """Update an existing classification"""
        classification = Classification.objects.select_related('survey').get(pk=id)

        for field, value in input_to_dict(input, exclude=['translations']).items():
            setattr(classification, field, value)

        classification.save()

        if input.translations:
            for trans_input in input.translations:
                ClassificationTranslation.objects.update_or_create(
                    classification=classification,
                    language=trans_input.language,
                    defaults={'name': trans_input.name},
                )

        return classification

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_classification_id, 'update')
    def delete_classification(
        self,
        info: Info,
        id: int,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> OperationResult:
        """Soft delete a classification"""
        classification = Classification.objects.get(pk=id)
        classification.deleted_at = now()
        classification.save()
        return OperationResult(success=True)

    # ==================== Recommendation Mutations ====================

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_survey_id, 'update')
    def create_recommendation(
        self,
        info: Info,
        survey_id: int,
        input: RecommendationInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> RecommendationType:
        """Create a new recommendation for a survey"""
        survey = Survey.objects.get(pk=survey_id)

        data = {'survey': survey, 'description': input.description}
        if input.option_id is not strawberry.UNSET:
            data['option'] = AnswerSchemaOption.objects.get(pk=input.option_id, survey=survey)

        recommendation = Recommendation.objects.create(**data)

        if input.translations:
            for trans_input in input.translations:
                RecommendationTranslation.objects.create(
                    recommendation=recommendation,
                    language=trans_input.language,
                    description=trans_input.description,
                )

        return recommendation

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_recommendation_id, 'update')
    def update_recommendation(
        self,
        info: Info,
        id: int,
        input: RecommendationInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> RecommendationType:
        """Update an existing recommendation"""
        recommendation = Recommendation.objects.select_related('survey').get(pk=id)

        recommendation.description = input.description
        if input.option_id is not strawberry.UNSET:
            recommendation.option = AnswerSchemaOption.objects.get(pk=input.option_id, survey=recommendation.survey)

        recommendation.save()

        if input.translations:
            for trans_input in input.translations:
                RecommendationTranslation.objects.update_or_create(
                    recommendation=recommendation,
                    language=trans_input.language,
                    defaults={'description': trans_input.description},
                )

        return recommendation

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_recommendation_id, 'update')
    def delete_recommendation(
        self,
        info: Info,
        id: int,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> OperationResult:
        """Soft delete a recommendation"""
        recommendation = Recommendation.objects.get(pk=id)
        recommendation.deleted_at = now()
        recommendation.save()
        return OperationResult(success=True)

    # ==================== Action Mutations ====================

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_survey_id, 'update')
    def create_action(
        self,
        info: Info,
        survey_id: int,
        input: ActionInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> ActionType:
        """Create a new action for a survey"""
        survey = Survey.objects.get(pk=survey_id)

        data = input_to_dict(input, exclude=['translations'])
        data['survey'] = survey

        action = Action.objects.create(**data)

        if input.translations:
            for trans_input in input.translations:
                ActionTranslation.objects.create(
                    action=action,
                    language=trans_input.language,
                    title=trans_input.title,
                    description=trans_input.description,
                )

        return action

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_action_id, 'update')
    def update_action(
        self,
        info: Info,
        id: int,
        input: ActionInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> ActionType:
        """Update an existing action"""
        action = Action.objects.select_related('survey').get(pk=id)

        for field, value in input_to_dict(input, exclude=['translations']).items():
            setattr(action, field, value)

        action.save()

        if input.translations:
            for trans_input in input.translations:
                ActionTranslation.objects.update_or_create(
                    action=action,
                    language=trans_input.language,
                    defaults={
                        'title': trans_input.title,
                        'description': trans_input.description,
                    },
                )

        return action

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_action_id, 'update')
    def delete_action(
        self,
        info: Info,
        id: int,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> OperationResult:
        """Delete an action"""
        action = Action.objects.get(pk=id)
        action.delete()
        return OperationResult(success=True)
