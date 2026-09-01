import strawberry
import strawberry_django
from strawberry.types import Info
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ObjectDoesNotExist
from django.utils.timezone import now

from app.auth_utils import with_django_user
from app.permissions import check_permission
from app.schema_common import RequireAuth, OperationResult
from pricing.services import upsert_prices_for_parent
from survey_collections.inputs import SurveyCollectionInput
from survey_collections.types import SurveyCollectionType
from survey_collections.models import SurveyCollection, SurveyCollectionTranslation
from surveys.models import Survey
from surveys.schemas.utils import input_to_dict
from taxonomy.models import Category
from app.graphql_ids import as_pk


def _type_from_survey_id(info, survey_id, **kw):
    return Survey.objects.values_list('survey_type', flat=True).get(pk=survey_id)


@strawberry.type
class SurveyCollectionMutations:
    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    def create_survey_collection(
        self,
        info: Info,
        input: SurveyCollectionInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SurveyCollectionType:
        data = input_to_dict(input, exclude=['category_id', 'translations', 'prices'])
        if input.category_id is not strawberry.UNSET and input.category_id is not None:
            try:
                data['category'] = Category.objects.get(category_id=input.category_id)
            except Category.DoesNotExist:
                raise ObjectDoesNotExist(f"Category not found: {input.category_id}")

        collection = SurveyCollection.objects.create(**data)

        if input.translations:
            for trans_input in input.translations:
                SurveyCollectionTranslation.objects.create(
                    collection=collection,
                    language=trans_input.language,
                    title=trans_input.title,
                    description=trans_input.description,
                    short_description=trans_input.short_description,
                    slug=trans_input.slug,
                )

        if input.prices is not strawberry.UNSET and input.prices:
            upsert_prices_for_parent(collection, input.prices)

        return collection

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    def update_survey_collection(
        self,
        info: Info,
        id: strawberry.ID,
        input: SurveyCollectionInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SurveyCollectionType:
        id = as_pk(id)
        collection = SurveyCollection.objects.get(pk=id)

        for field, value in input_to_dict(input, exclude=['category_id', 'translations', 'prices']).items():
            setattr(collection, field, value)
        if input.category_id is not strawberry.UNSET:
            if input.category_id:
                try:
                    collection.category = Category.objects.get(category_id=input.category_id)
                except Category.DoesNotExist:
                    raise ObjectDoesNotExist(f"Category not found: {input.category_id}")
            else:
                collection.category = None

        collection.save()

        if input.translations:
            for trans_input in input.translations:
                SurveyCollectionTranslation.objects.update_or_create(
                    collection=collection,
                    language=trans_input.language,
                    defaults={
                        'title': trans_input.title,
                        'description': trans_input.description,
                        'short_description': trans_input.short_description,
                        'slug': trans_input.slug,
                    }
                )

        if input.prices is not strawberry.UNSET and input.prices:
            upsert_prices_for_parent(collection, input.prices)

        return collection

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    def delete_survey_collection(
        self,
        info: Info,
        id: strawberry.ID,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> OperationResult:
        id = as_pk(id)
        collection = SurveyCollection.objects.get(pk=id)
        collection.deleted_at = now()
        collection.save()
        return OperationResult(success=True)

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_survey_id, 'update')
    def add_survey_to_collection(
        self,
        info: Info,
        collection_id: strawberry.ID,
        survey_id: strawberry.ID,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SurveyCollectionType:
        collection_id = as_pk(collection_id)
        survey_id = as_pk(survey_id)
        collection = SurveyCollection.objects.get(pk=collection_id)
        survey = Survey.objects.get(pk=survey_id)
        collection.assessments.add(survey)
        return collection

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_survey_id, 'update')
    def remove_survey_from_collection(
        self,
        info: Info,
        collection_id: strawberry.ID,
        survey_id: strawberry.ID,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SurveyCollectionType:
        collection_id = as_pk(collection_id)
        survey_id = as_pk(survey_id)
        collection = SurveyCollection.objects.get(pk=collection_id)
        survey = Survey.objects.get(pk=survey_id)
        collection.assessments.remove(survey)
        return collection
