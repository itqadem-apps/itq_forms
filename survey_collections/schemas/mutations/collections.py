import strawberry
import strawberry_django
from strawberry.types import Info
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ObjectDoesNotExist
from django.utils.timezone import now

from app.auth_utils import with_django_user
from app.permissions import check_permission
from app.platform import ensure_in_org
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
    @check_permission('collection', 'create')
    def create_survey_collection(
        self,
        info: Info,
        input: SurveyCollectionInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SurveyCollectionType:
        data = input_to_dict(input, exclude=['category_id', 'translations', 'prices'])

        # The owning organization is bound from the caller's auth context, never
        # taken from client input — the same contract create_survey follows, see
        # SPEC-forms-permission-gates CAP-1. `check_permission` above has already
        # refused a caller with no org context, so this cannot be None.
        data['organization_id'] = info.context.auth_context.organization_id.value

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
    @check_permission('collection', 'update')
    def update_survey_collection(
        self,
        info: Info,
        id: strawberry.ID,
        input: SurveyCollectionInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SurveyCollectionType:
        id = as_pk(id)
        collection = SurveyCollection.objects.get(pk=id)
        # SPEC-forms-permission-gates CAP-2: holding the key is not enough — the
        # row must belong to the caller's organization. `check_permission` has
        # already guaranteed an auth context here.
        ensure_in_org(collection, info.context.auth_context)

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
    @check_permission('collection', 'delete')
    def delete_survey_collection(
        self,
        info: Info,
        id: strawberry.ID,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> OperationResult:
        id = as_pk(id)
        collection = SurveyCollection.objects.get(pk=id)
        ensure_in_org(collection, info.context.auth_context)
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
        # Both sides are gated: membership joins two rows, so either one being
        # another organization's is a cross-tenant write.
        ensure_in_org(collection, info.context.auth_context)
        ensure_in_org(survey, info.context.auth_context)
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
        # Both sides are gated: membership joins two rows, so either one being
        # another organization's is a cross-tenant write.
        ensure_in_org(collection, info.context.auth_context)
        ensure_in_org(survey, info.context.auth_context)
        collection.assessments.remove(survey)
        return collection
