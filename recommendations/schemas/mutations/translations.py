import strawberry
import strawberry_django
from strawberry.types import Info
from django.contrib.auth.base_user import AbstractBaseUser
from uuid import UUID

from app.auth_utils import with_django_user
from app.permissions import check_permission
from recommendations.inputs import RecommendationTranslationInput, ActionTranslationInput
from recommendations.types import RecommendationTranslationType, ActionTranslationType
from recommendations.models import (
    Recommendation,
    RecommendationTranslation,
    Action,
    ActionTranslation,
)
from app.schema_common import RequireAuth, OperationResult


def _type_from_recommendation_id(info, recommendation_id, **kw):
    return Recommendation.objects.select_related('survey').get(pk=recommendation_id).survey.survey_type


def _type_from_recommendation_translation_id(info, id, **kw):
    return RecommendationTranslation.objects.select_related('recommendation__survey').get(pk=id).recommendation.survey.survey_type


def _type_from_action_id(info, action_id, **kw):
    return Action.objects.select_related('survey').get(pk=action_id).survey.survey_type


def _type_from_action_translation_id(info, id, **kw):
    return ActionTranslation.objects.select_related('action__survey').get(pk=id).action.survey.survey_type


@strawberry.type
class RecommendationTranslationMutations:

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_recommendation_id, 'update')
    def create_recommendation_translation(
        self,
        info: Info,
        recommendation_id: int,
        input: RecommendationTranslationInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> RecommendationTranslationType:
        recommendation = Recommendation.objects.get(pk=recommendation_id)
        translation = RecommendationTranslation.objects.create(
            recommendation=recommendation,
            language=input.language,
            description=input.description,
        )
        return translation

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_recommendation_translation_id, 'update')
    def update_recommendation_translation(
        self,
        info: Info,
        id: UUID,
        input: RecommendationTranslationInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> RecommendationTranslationType:
        translation = RecommendationTranslation.objects.select_related('recommendation__survey').get(pk=id)

        if input.language:
            translation.language = input.language
        if input.description is not None:
            translation.description = input.description

        translation.save()
        return translation

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_recommendation_translation_id, 'update')
    def delete_recommendation_translation(
        self,
        info: Info,
        id: UUID,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> OperationResult:
        translation = RecommendationTranslation.objects.get(pk=id)
        translation.delete()
        return OperationResult(success=True)


@strawberry.type
class ActionTranslationMutations:

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_action_id, 'update')
    def create_action_translation(
        self,
        info: Info,
        action_id: int,
        input: ActionTranslationInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> ActionTranslationType:
        action = Action.objects.get(pk=action_id)
        translation = ActionTranslation.objects.create(
            action=action,
            language=input.language,
            title=input.title,
            description=input.description,
        )
        return translation

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_action_translation_id, 'update')
    def update_action_translation(
        self,
        info: Info,
        id: UUID,
        input: ActionTranslationInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> ActionTranslationType:
        translation = ActionTranslation.objects.select_related('action__survey').get(pk=id)

        if input.language:
            translation.language = input.language
        if input.title is not None:
            translation.title = input.title
        if input.description is not None:
            translation.description = input.description

        translation.save()
        return translation

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_action_translation_id, 'update')
    def delete_action_translation(
        self,
        info: Info,
        id: UUID,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> OperationResult:
        translation = ActionTranslation.objects.get(pk=id)
        translation.delete()
        return OperationResult(success=True)
