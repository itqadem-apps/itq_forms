import strawberry
import strawberry_django
from strawberry.types import Info
from django.contrib.auth.base_user import AbstractBaseUser
from typing import List

from django.db import transaction

from app.auth_utils import with_django_user
from app.permissions import check_permission
from surveys.flow import assert_survey_forward, validate_edge
from surveys.inputs import AnswerSchemaInput, AnswerSchemaOptionInput
from surveys.types import AnswerSchemaType, AnswerSchemaOptionType
from surveys.models import (
    Question,
    AnswerSchema,
    AnswerSchemaOption,
    AnswerSchemaOptionTranslation,
    Classification,
    Survey,
)
from ..common import RequireAuth, OperationResult
from ..utils import input_to_dict
from app.graphql_ids import as_pk


def _type_from_schema_id(info, schema_id=None, id=None, **kw):
    pk = schema_id or id
    return AnswerSchema.objects.select_related('survey').get(pk=pk).survey.survey_type


def _type_from_option_id(info, id, **kw):
    return AnswerSchemaOption.objects.select_related('survey').get(pk=id).survey.survey_type


def _store_option(option: AnswerSchemaOption, input: AnswerSchemaOptionInput) -> None:
    """Save `option` with the edge `input` gives it (`forms:AD-3`), then refuse the write if any
    edge of the survey now points backwards (`forms:AD-5`). The caller's transaction rolls it back."""
    if input.flow_action is not strawberry.UNSET:
        option.flow_action = input.flow_action
    if input.flow_target_id is not strawberry.UNSET:
        option.flow_target_id = as_pk(input.flow_target_id) if input.flow_target_id is not None else None
    validate_edge(option)
    option.save()
    assert_survey_forward(option.survey)


@strawberry.type
class AnswerSchemaMutations:
    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_schema_id, 'update')
    def update_answer_schema(
        self,
        info: Info,
        id: strawberry.ID,
        input: AnswerSchemaInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> AnswerSchemaType:
        """Update an answer schema"""
        id = as_pk(id)
        schema = AnswerSchema.objects.select_related('survey', 'question').get(pk=id)

        for field, value in input_to_dict(input).items():
            setattr(schema, field, value)

        schema.save()
        return schema

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_schema_id, 'update')
    @transaction.atomic
    def create_answer_schema_option(
        self,
        info: Info,
        schema_id: strawberry.ID,
        input: AnswerSchemaOptionInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> AnswerSchemaOptionType:
        """Create a new answer schema option"""
        schema_id = as_pk(schema_id)
        schema = AnswerSchema.objects.select_related('survey', 'section', 'question').get(pk=schema_id)
        Survey.objects.select_for_update().filter(pk=schema.survey_id).first()

        data = input_to_dict(input, exclude=['classification_id', 'translations', 'flow_action', 'flow_target_id'])
        data.update(survey=schema.survey, section=schema.section, question=schema.question, schema=schema)
        if input.classification_id is not strawberry.UNSET:
            data['classification'] = (
                Classification.objects.get(pk=input.classification_id, survey=schema.survey)
                if input.classification_id is not None
                else None
            )

        option = AnswerSchemaOption(**data)
        _store_option(option, input)

        # Create translations
        if input.translations:
            for trans_input in input.translations:
                AnswerSchemaOptionTranslation.objects.create(
                    option=option,
                    language=trans_input.language,
                    text=trans_input.text,
                )

        return option

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_option_id, 'update')
    @transaction.atomic
    def update_answer_schema_option(
        self,
        info: Info,
        id: strawberry.ID,
        input: AnswerSchemaOptionInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> AnswerSchemaOptionType:
        """Update an existing answer schema option"""
        id = as_pk(id)
        option = AnswerSchemaOption.objects.select_related('survey', 'schema').get(pk=id)
        Survey.objects.select_for_update().filter(pk=option.survey_id).first()

        for field, value in input_to_dict(input, exclude=['classification_id', 'translations', 'flow_action', 'flow_target_id']).items():
            setattr(option, field, value)
        if input.classification_id is not strawberry.UNSET:
            option.classification = (
                Classification.objects.get(pk=input.classification_id, survey=option.survey)
                if input.classification_id is not None
                else None
            )

        _store_option(option, input)

        # Update translations if provided
        if input.translations:
            for trans_input in input.translations:
                AnswerSchemaOptionTranslation.objects.update_or_create(
                    option=option,
                    language=trans_input.language,
                    defaults={
                        'text': trans_input.text,
                    }
                )

        return option

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_option_id, 'update')
    def delete_answer_schema_option(
        self,
        info: Info,
        id: strawberry.ID,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> OperationResult:
        """Delete an answer schema option"""
        id = as_pk(id)
        option = AnswerSchemaOption.objects.get(pk=id)
        option.delete()
        return OperationResult(success=True)

    @strawberry.mutation(permission_classes=[RequireAuth])
    @with_django_user
    @check_permission(_type_from_schema_id, 'update')
    def reorder_answer_schema_options(
        self,
        info: Info,
        schema_id: strawberry.ID,
        option_ids: List[int],
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> List[AnswerSchemaOptionType]:
        """Reorder answer schema options"""
        schema_id = as_pk(schema_id)
        schema = AnswerSchema.objects.select_related('survey').get(pk=schema_id)

        # Validate all option IDs belong to the schema
        options = AnswerSchemaOption.objects.filter(id__in=option_ids, schema=schema)
        if options.count() != len(option_ids):
            raise ValueError("Some option IDs are invalid or don't belong to this schema")

        # Update order
        option_map = {option.id: option for option in options}
        for order, option_id in enumerate(option_ids, start=1):
            option = option_map.get(option_id)
            if option:
                option.order = order
                option.save(update_fields=['order'])

        return list(AnswerSchemaOption.objects.filter(schema=schema).order_by('order'))
