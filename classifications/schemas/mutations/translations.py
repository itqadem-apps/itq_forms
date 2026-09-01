import strawberry
import strawberry_django
from strawberry.types import Info
from django.contrib.auth.base_user import AbstractBaseUser
from uuid import UUID

from app.auth_utils import with_django_user
from app.permissions import check_permission
from classifications.inputs import ClassificationTranslationInput
from classifications.types import ClassificationTranslationType
from classifications.models import Classification, ClassificationTranslation
from app.schema_common import RequireAuth, OperationResult
from app.graphql_ids import as_pk


def _type_from_classification_id(info, classification_id, **kw):
    return Classification.objects.select_related('survey').get(pk=classification_id).survey.survey_type


def _type_from_classification_translation_id(info, id, **kw):
    return ClassificationTranslation.objects.select_related('classification__survey').get(pk=id).classification.survey.survey_type


@strawberry.type
class ClassificationTranslationMutations:

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_classification_id, 'update')
    def create_classification_translation(
        self,
        info: Info,
        classification_id: strawberry.ID,
        input: ClassificationTranslationInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> ClassificationTranslationType:
        classification_id = as_pk(classification_id)
        classification = Classification.objects.get(pk=classification_id)
        translation = ClassificationTranslation.objects.create(
            classification=classification,
            language=input.language,
            name=input.name,
        )
        return translation

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_classification_translation_id, 'update')
    def update_classification_translation(
        self,
        info: Info,
        id: UUID,
        input: ClassificationTranslationInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> ClassificationTranslationType:
        translation = ClassificationTranslation.objects.select_related('classification__survey').get(pk=id)
        if input.language:
            translation.language = input.language
        if input.name is not None:
            translation.name = input.name
        translation.save()
        return translation

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_classification_translation_id, 'update')
    def delete_classification_translation(
        self,
        info: Info,
        id: UUID,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> OperationResult:
        translation = ClassificationTranslation.objects.get(pk=id)
        translation.delete()
        return OperationResult(success=True)
