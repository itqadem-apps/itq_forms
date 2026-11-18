from typing import List

import strawberry
import strawberry_django
from strawberry.types import Info
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from django.utils.timezone import now

from app.auth_utils import with_django_user
from app.permissions import Permission, check_permission, holds
from app.schema_common import RequireAuth, OperationResult
from media.claims import ARTWORK_SLOTS, require_claimed
from pricing.services import upsert_prices_for_parent
from survey_collections import rule_report
from survey_collections.inputs import SurveyCollectionInput
from survey_collections.types import SurveyCollectionType
from survey_collections.models import CollectionMembership, SurveyCollection, SurveyCollectionTranslation
from surveys.models import Survey
from surveys.schemas.utils import input_to_dict
from taxonomy.models import Category
from app.graphql_ids import as_pk
from app.platform import ensure_in_org


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
        # RequireAuth proves identity only, and collections are not a
        # PERMISSION_MAP kind, so check_permission cannot gate this resolver:
        # the org context and the key are both checked here, before claims or
        # any write. A context alone is not staff (estate:AD-29): every user is
        # a roleless member of Itqadem. A null-owned row is what the CAP-2 row
        # gate refuses to serve back, and what migration 0040 had to repair.
        auth_ctx = getattr(info.context, "auth_context", None)
        if auth_ctx is None:
            raise PermissionError("Missing X-Organization-Id header")
        if not holds(auth_ctx, Permission.COLLECTION_CREATE.value):
            raise PermissionError(
                f"Permission denied. Required permission: {Permission.COLLECTION_CREATE.value}"
            )

        data = input_to_dict(input, exclude=['category_id', 'translations', 'prices'])
        require_claimed(info, data, ARTWORK_SLOTS)

        # The owning organization is bound from the caller's auth context, never
        # taken from client input — the same contract create_survey follows, see
        # SPEC-forms-permission-gates CAP-1.
        data['organization_id'] = auth_ctx.organization_id.value

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

        data = input_to_dict(input, exclude=['category_id', 'translations', 'prices'])
        require_claimed(info, data, ARTWORK_SLOTS, collection)
        for field, value in data.items():
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
        with transaction.atomic():
            # Lock the survey so two adds of one curriculum to two collections cannot both pass
            # the one-collection check before either is stored.
            list(Survey.objects.select_for_update().filter(pk=survey.pk).values_list("pk", flat=True))
            refused = rule_report.refusal(collection, survey)
            if refused is not None:
                raise ValidationError(refused)
            collection.append_member(survey)
        return collection

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @transaction.atomic
    def reorder_collection_surveys(
        self,
        info: Info,
        collection_id: strawberry.ID,
        survey_ids: List[strawberry.ID],
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SurveyCollectionType:
        """Save a collection's member order: `survey_ids` names every live member once."""
        auth_ctx = getattr(info.context, "auth_context", None)
        if auth_ctx is None:
            raise PermissionError("Missing X-Organization-Id header")
        if not holds(auth_ctx, Permission.COLLECTION_UPDATE.value):
            raise PermissionError(
                f"Permission denied. Required permission: {Permission.COLLECTION_UPDATE.value}"
            )
        collection = SurveyCollection.objects.select_for_update().get(
            pk=as_pk(collection_id), deleted_at__isnull=True
        )
        ensure_in_org(collection, auth_ctx)

        wanted = [as_pk(i) for i in survey_ids]
        memberships = list(
            CollectionMembership.objects.filter(surveycollection=collection)
            .select_related("survey")
            .order_by("order", "id")
        )
        live = {m.survey_id: m for m in memberships if m.survey.deleted_at is None}
        if len(wanted) != len(set(wanted)) or set(wanted) != set(live):
            raise ValidationError(
                "The new order must name every survey in the collection exactly once."
            )

        # Soft-deleted members are never shown, so they keep their relative place after the rest.
        ordered = [live[i] for i in wanted] + [m for m in memberships if m.survey_id not in live]
        for position, membership in enumerate(ordered):
            membership.order = position
        CollectionMembership.objects.bulk_update(ordered, ["order"])
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
