import strawberry
import strawberry_django
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from strawberry import UNSET
from strawberry.types import Info

from app.auth_utils import with_django_user
from app.permissions import check_permission
from surveys.inputs import SurveyCreateInput, SurveyUpdateInput
from surveys.types import SurveyType
from surveys.types.survey import SurveyPayload
from app.messaging import publish
from external_references.models import ExternalReference
from pricing.services import upsert_prices_for_parent
from surveys.events import (
    SurveyCreated,
    SurveyDeleted,
    SurveyPublished,
    SurveyUnpublished,
    SurveyUpdated,
)
from surveys.messaging import build_survey_payload_or_log
from classifications.models import Classification, ClassificationTranslation
from recommendations.models import Recommendation, RecommendationTranslation, Action, ActionTranslation
from surveys.models import (
    Survey,
    SurveyTranslation,
    SectionTranslation,
    Question,
    QuestionTranslation,
    AnswerSchemaOption,
    AnswerSchemaOptionTranslation,
)
from taxonomy.models import Category
from ..common import RequireAuth, OperationResult
from ..utils import input_to_dict, clone_instance
from app.graphql_ids import as_pk


def _type_from_input(info, input, **kw):
    return input.survey_type or 'survey'


def _type_from_survey_id(info, id, **kw):
    return Survey.objects.values_list('survey_type', flat=True).get(pk=id)


def _type_from_update_input(info, input, **kw):
    return Survey.objects.values_list('survey_type', flat=True).get(pk=input.id)


@strawberry.type
class SurveyMutations:
    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_input, 'create')
    @transaction.atomic
    def create_survey(
        self,
        info: Info,
        input: SurveyCreateInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SurveyPayload:
        data = input_to_dict(input, exclude=['category_id', 'translations', 'external_reference', 'prices'])

        if input.category_id is not UNSET and input.category_id is not None:
            try:
                data['category'] = Category.objects.get(category_id=input.category_id)
            except Category.DoesNotExist:
                raise ObjectDoesNotExist(f"Category not found: {input.category_id}")

        target_collection = None
        if input.external_reference is not UNSET and input.external_reference is not None:
            ref = (
                ExternalReference.objects
                .select_related("collection")
                .filter(
                    source_service=input.external_reference.source_service,
                    source_model=input.external_reference.source_model,
                    source_id=input.external_reference.source_id,
                    collection__isnull=False,
                )
                .first()
            )
            if ref is None:
                raise ObjectDoesNotExist(
                    f"External reference not found or has no collection: "
                    f"{input.external_reference.source_service}:"
                    f"{input.external_reference.source_model}:"
                    f"{input.external_reference.source_id}"
                )
            target_collection = ref.collection

        survey = Survey.objects.create(**data)

        if target_collection is not None:
            target_collection.assessments.add(survey)

        if input.translations is not UNSET and input.translations:
            for t in input.translations:
                SurveyTranslation.objects.create(survey=survey, **input_to_dict(t))

        if input.prices is not UNSET and input.prices:
            upsert_prices_for_parent(survey, input.prices)

        payload = build_survey_payload_or_log(survey, "SurveyCreated")
        if payload is not None:
            publish(SurveyCreated(
                aggregate_id=survey.pk,
                organization_id=payload["organization_id"],
                survey=payload,
            ))

        return SurveyPayload(success=True, message=None, survey=survey)

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_update_input, 'update')
    @transaction.atomic
    def update_survey(
        self,
        info: Info,
        input: SurveyUpdateInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SurveyPayload:
        survey = Survey.objects.get(pk=input.id)

        data = input_to_dict(input, exclude=['id', 'category_id', 'translations', 'prices'])
        for field, value in data.items():
            setattr(survey, field, value)

        if input.category_id is not UNSET:
            if input.category_id:
                try:
                    survey.category = Category.objects.get(category_id=input.category_id)
                except Category.DoesNotExist:
                    raise ObjectDoesNotExist(f"Category not found: {input.category_id}")
            else:
                survey.category = None

        survey.save()

        if input.translations is not UNSET and input.translations:
            for t in input.translations:
                t_data = input_to_dict(t, exclude=['id'])
                language = t_data.pop('language', None)
                if language:
                    SurveyTranslation.objects.update_or_create(
                        survey=survey, language=language, defaults=t_data
                    )

        if input.prices is not UNSET and input.prices:
            upsert_prices_for_parent(survey, input.prices)

        payload = build_survey_payload_or_log(survey, "SurveyUpdated")
        if payload is not None:
            publish(SurveyUpdated(
                aggregate_id=survey.pk,
                organization_id=payload["organization_id"],
                survey=payload,
            ))

        return SurveyPayload(success=True, message=None, survey=survey)

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_survey_id, 'delete')
    def delete_survey(
        self,
        info: Info,
        id: strawberry.ID,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> OperationResult:
        id = as_pk(id)
        survey = Survey.objects.get(pk=id)
        payload = build_survey_payload_or_log(survey, "SurveyDeleted")
        if payload is not None:
            publish(SurveyDeleted(
                aggregate_id=survey.pk,
                organization_id=payload["organization_id"],
                survey=payload,
            ))
        survey.delete()
        return OperationResult(success=True)

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_survey_id, 'create')
    @transaction.atomic
    def duplicate_survey(
        self,
        info: Info,
        id: strawberry.ID,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SurveyPayload:
        id = as_pk(id)
        original = Survey.objects.get(pk=id)

        new_survey = clone_instance(original)

        # Duplicate survey translations
        for t in original.translations.all():
            clone_instance(
                t,
                survey=new_survey,
                title=f"{t.title} (Copy)" if t.title else None,
                slug=f"{t.slug}-copy" if t.slug else None,
            )

        # Duplicate sections → questions → schemas → options (with all translations)
        for section in original.sections.all():
            new_section = clone_instance(section, survey=new_survey)

            for t in SectionTranslation.objects.filter(section=section):
                clone_instance(t, section=new_section)

            for question in Question.objects.filter(section=section):
                new_question = clone_instance(question, survey=new_survey, section=new_section)

                for t in QuestionTranslation.objects.filter(question=question):
                    clone_instance(t, question=new_question)

                if hasattr(question, 'answer_schema'):
                    old_schema = question.answer_schema
                    new_schema = clone_instance(
                        old_schema,
                        survey=new_survey,
                        section=new_section,
                        question=new_question,
                    )
                    for option in AnswerSchemaOption.objects.filter(schema=old_schema):
                        new_option = clone_instance(
                            option,
                            survey=new_survey,
                            section=new_section,
                            question=new_question,
                            schema=new_schema,
                        )
                        for t in AnswerSchemaOptionTranslation.objects.filter(option=option):
                            clone_instance(t, option=new_option)

        # Duplicate classifications
        for classification in original.classifications.all():
            new_classification = clone_instance(classification, survey=new_survey)
            for t in ClassificationTranslation.objects.filter(classification=classification):
                clone_instance(t, classification=new_classification)

        # Duplicate recommendations
        for recommendation in original.recommendations.all():
            new_recommendation = clone_instance(recommendation, survey=new_survey)
            for t in RecommendationTranslation.objects.filter(recommendation=recommendation):
                clone_instance(t, recommendation=new_recommendation)

        # Duplicate actions
        for action in original.actions.all():
            new_action = clone_instance(action, survey=new_survey)
            for t in ActionTranslation.objects.filter(action=action):
                clone_instance(t, action=new_action)

        return SurveyPayload(success=True, message=None, survey=new_survey)

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_survey_id, 'update')
    def update_survey_status(
        self,
        info: Info,
        id: strawberry.ID,
        status: str,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SurveyType:
        id = as_pk(id)
        survey = Survey.objects.get(pk=id)
        old_status = survey.status
        survey.status = status
        survey.save(update_fields=["status"])
        if survey.status == Survey.STATUS_PUBLISHED:
            event_cls = SurveyPublished
            event_name = "SurveyPublished"
        elif survey.status in {Survey.STATUS_DRAFT, Survey.STATUS_ARCHIVED, Survey.STATUS_SUSPENDED}:
            event_cls = SurveyUnpublished
            event_name = "SurveyUnpublished"
        else:
            event_cls = SurveyUpdated
            event_name = "SurveyUpdated"
        payload = build_survey_payload_or_log(survey, event_name)
        if payload is not None:
            publish(event_cls(
                aggregate_id=survey.pk,
                organization_id=payload["organization_id"],
                survey=payload,
            ))

        if old_status != survey.status:
            from surveys.media_access import promote_survey_assets, demote_survey_assets
            if survey.status == Survey.STATUS_PUBLISHED:
                promote_survey_assets(survey.pk)
            elif survey.status in {Survey.STATUS_DRAFT, Survey.STATUS_ARCHIVED, Survey.STATUS_SUSPENDED}:
                demote_survey_assets(survey.pk)

        return survey
