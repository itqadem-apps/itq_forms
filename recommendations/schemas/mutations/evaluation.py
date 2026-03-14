import strawberry
import strawberry_django
from strawberry.types import Info
from django.contrib.auth.base_user import AbstractBaseUser
from django.utils.timezone import now

from app.auth_utils import with_django_user
from app.permissions import check_permission
from recommendations.inputs import RecommendationInput, ActionInput
from recommendations.types import RecommendationType, ActionType
from recommendations.models import (
    Recommendation,
    RecommendationTranslation,
    Action,
    ActionTranslation,
)
from surveys.models import Survey, AnswerSchemaOption
from app.schema_common import RequireAuth, OperationResult
from surveys.schemas.utils import input_to_dict


def _type_from_survey_id(info, survey_id, **kw):
    return Survey.objects.values_list('survey_type', flat=True).get(pk=survey_id)


def _type_from_recommendation_id(info, id, **kw):
    return Recommendation.objects.select_related('survey').get(pk=id).survey.survey_type


def _type_from_action_id(info, id, **kw):
    return Action.objects.select_related('survey').get(pk=id).survey.survey_type


@strawberry.type
class RecommendationMutations:

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
        survey = Survey.objects.get(pk=survey_id)

        data = {'survey': survey}
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
        recommendation = Recommendation.objects.select_related('survey').get(pk=id)

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
        recommendation = Recommendation.objects.get(pk=id)
        recommendation.deleted_at = now()
        recommendation.save()
        return OperationResult(success=True)


@strawberry.type
class ActionMutations:

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
        action = Action.objects.get(pk=id)
        action.delete()
        return OperationResult(success=True)
