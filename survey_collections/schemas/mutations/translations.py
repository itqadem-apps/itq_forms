import strawberry
import strawberry_django
from strawberry.types import Info
from django.contrib.auth.base_user import AbstractBaseUser

from app.auth_utils import with_django_user
from app.schema_common import RequireAuth, OperationResult
from survey_collections.inputs import SurveyCollectionTranslationInput
from survey_collections.types import SurveyCollectionTranslationType
from survey_collections.models import SurveyCollection, SurveyCollectionTranslation


@strawberry.type
class SurveyCollectionTranslationMutations:

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    def create_survey_collection_translation(
        self,
        info: Info,
        collection_id: int,
        input: SurveyCollectionTranslationInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SurveyCollectionTranslationType:
        collection = SurveyCollection.objects.get(pk=collection_id)
        translation = SurveyCollectionTranslation.objects.create(
            collection=collection,
            language=input.language,
            title=input.title,
            description=input.description,
            short_description=input.short_description,
            slug=input.slug,
        )
        return translation

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    def update_survey_collection_translation(
        self,
        info: Info,
        id: int,
        input: SurveyCollectionTranslationInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SurveyCollectionTranslationType:
        translation = SurveyCollectionTranslation.objects.get(pk=id)

        if input.language:
            translation.language = input.language
        if input.title is not None:
            translation.title = input.title
        if input.description is not None:
            translation.description = input.description
        if input.short_description is not None:
            translation.short_description = input.short_description
        if input.slug is not None:
            translation.slug = input.slug

        translation.save()
        return translation

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    def delete_survey_collection_translation(
        self,
        info: Info,
        id: int,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> OperationResult:
        translation = SurveyCollectionTranslation.objects.get(pk=id)
        translation.delete()
        return OperationResult(success=True)
