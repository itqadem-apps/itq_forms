import strawberry
import strawberry_django
from strawberry.types import Info
from django.contrib.auth.base_user import AbstractBaseUser
from django.utils.timezone import now

from app.auth_utils import with_django_user
from app.permissions import check_permission
from classifications.inputs import ClassificationInput
from classifications.types import ClassificationType
from classifications.models import Classification, ClassificationTranslation
from surveys.models import Survey
from app.schema_common import RequireAuth, OperationResult
from surveys.schemas.utils import input_to_dict
from app.graphql_ids import as_pk


def _type_from_survey_id(info, survey_id, **kw):
    return Survey.objects.values_list('survey_type', flat=True).get(pk=survey_id)


def _type_from_classification_id(info, id, **kw):
    return Classification.objects.select_related('survey').get(pk=id).survey.survey_type


@strawberry.type
class ClassificationMutations:

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_survey_id, 'update')
    def create_classification(
        self,
        info: Info,
        survey_id: strawberry.ID,
        input: ClassificationInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> ClassificationType:
        survey_id = as_pk(survey_id)
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
        id: strawberry.ID,
        input: ClassificationInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> ClassificationType:
        id = as_pk(id)
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
        id: strawberry.ID,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> OperationResult:
        id = as_pk(id)
        classification = Classification.objects.get(pk=id)
        classification.deleted_at = now()
        classification.save()
        return OperationResult(success=True)
