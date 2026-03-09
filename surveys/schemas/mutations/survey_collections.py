import strawberry
import strawberry_django
from django.contrib.auth.base_user import AbstractBaseUser
from django.utils.timezone import now

from app.auth_utils import with_django_user
from app.permissions import check_permission
from surveys.inputs import SurveyCollectionInput
from surveys.types import SurveyCollectionType
from survey_collections.models import SurveyCollection, SurveyCollectionTranslation
from surveys.models import Survey
from taxonomy.models import Category
from ..common import RequireAuth, OperationResult
from ..utils import input_to_dict


def _type_from_survey_id(info, survey_id, **kw):
    return Survey.objects.values_list('survey_type', flat=True).get(pk=survey_id)


@strawberry.type
class SurveyCollectionMutations:
    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    def create_survey_collection(
        self,
        info,
        input: SurveyCollectionInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SurveyCollectionType:
        """Create a new survey collection"""
        data = input_to_dict(input, exclude=['category_id', 'translations'])
        if input.category_id is not strawberry.UNSET:
            data['category'] = Category.objects.get(category_id=input.category_id)

        collection = SurveyCollection.objects.create(**data)

        # Create translations
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

        return collection

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    def update_survey_collection(
        self,
        info,
        id: int,
        input: SurveyCollectionInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SurveyCollectionType:
        """Update an existing survey collection"""
        collection = SurveyCollection.objects.get(pk=id)

        for field, value in input_to_dict(input, exclude=['category_id', 'translations']).items():
            setattr(collection, field, value)
        if input.category_id is not strawberry.UNSET:
            collection.category = Category.objects.get(category_id=input.category_id)

        collection.save()

        # Update translations if provided
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

        return collection

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    def delete_survey_collection(
        self,
        info,
        id: int,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> OperationResult:
        """Soft delete a survey collection"""
        collection = SurveyCollection.objects.get(pk=id)
        collection.deleted_at = now()
        collection.save()
        return OperationResult(success=True)

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_survey_id, 'update')
    def add_survey_to_collection(
        self,
        info,
        collection_id: int,
        survey_id: int,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SurveyCollectionType:
        """Add a survey to a collection"""
        collection = SurveyCollection.objects.get(pk=collection_id)
        survey = Survey.objects.get(pk=survey_id)
        collection.assessments.add(survey)
        return collection

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_survey_id, 'update')
    def remove_survey_from_collection(
        self,
        info,
        collection_id: int,
        survey_id: int,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SurveyCollectionType:
        """Remove a survey from a collection"""
        collection = SurveyCollection.objects.get(pk=collection_id)
        survey = Survey.objects.get(pk=survey_id)
        collection.assessments.remove(survey)
        return collection
