import strawberry
import strawberry_django
from strawberry.types import Info
from django.contrib.auth.base_user import AbstractBaseUser
from uuid import UUID

from app.auth_utils import with_django_user
from app.permissions import check_permission
from surveys.inputs import (
    SurveyTranslationInput,
    SectionTranslationInput,
    QuestionTranslationInput,
    AnswerSchemaOptionTranslationInput,
    SurveyCollectionTranslationInput,
)
from surveys.types import (
    SurveyTranslationType,
    SectionTranslationType,
    QuestionTranslationType,
    AnswerSchemaOptionTranslationType,
    SurveyCollectionTranslationType,
)
from surveys.models import (
    Survey,
    SurveyTranslation,
    Section,
    SectionTranslation,
    Question,
    QuestionTranslation,
    AnswerSchemaOption,
    AnswerSchemaOptionTranslation,
)
from survey_collections.models import SurveyCollection, SurveyCollectionTranslation
from ..common import RequireAuth, OperationResult


# --- Type resolvers for @check_permission ---

def _type_from_survey_id(info, survey_id, **kw):
    return Survey.objects.values_list('survey_type', flat=True).get(pk=survey_id)


def _type_from_survey_translation_id(info, id, **kw):
    return SurveyTranslation.objects.select_related('survey').get(pk=id).survey.survey_type


def _type_from_section_id(info, section_id, **kw):
    return Section.objects.select_related('survey').get(pk=section_id).survey.survey_type


def _type_from_section_translation_id(info, id, **kw):
    return SectionTranslation.objects.select_related('section__survey').get(pk=id).section.survey.survey_type


def _type_from_question_id(info, question_id, **kw):
    return Question.objects.select_related('survey').get(pk=question_id).survey.survey_type


def _type_from_question_translation_id(info, id, **kw):
    return QuestionTranslation.objects.select_related('question__survey').get(pk=id).question.survey.survey_type


def _type_from_option_id(info, option_id, **kw):
    return AnswerSchemaOption.objects.select_related('survey').get(pk=option_id).survey.survey_type


def _type_from_option_translation_id(info, id, **kw):
    return AnswerSchemaOptionTranslation.objects.select_related('option__survey').get(pk=id).option.survey.survey_type


@strawberry.type
class TranslationMutations:
    # ==================== Survey Translations ====================

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_survey_id, 'update')
    def create_survey_translation(
        self,
        info: Info,
        survey_id: int,
        input: SurveyTranslationInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SurveyTranslationType:
        """Create a translation for a survey"""
        survey = Survey.objects.get(pk=survey_id)
        translation = SurveyTranslation.objects.create(
            survey=survey,
            language=input.language,
            title=input.title,
            description=input.description,
            short_description=input.short_description,
            slug=input.slug,
        )
        return translation

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_survey_translation_id, 'update')
    def update_survey_translation(
        self,
        info: Info,
        id: UUID,
        input: SurveyTranslationInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SurveyTranslationType:
        """Update a survey translation"""
        translation = SurveyTranslation.objects.select_related('survey').get(pk=id)

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
    @check_permission(_type_from_survey_translation_id, 'update')
    def delete_survey_translation(
        self,
        info: Info,
        id: UUID,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> OperationResult:
        """Delete a survey translation"""
        translation = SurveyTranslation.objects.get(pk=id)
        translation.delete()
        return OperationResult(success=True)

    # ==================== Section Translations ====================

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_section_id, 'update')
    def create_section_translation(
        self,
        info: Info,
        section_id: int,
        input: SectionTranslationInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SectionTranslationType:
        """Create a translation for a section"""
        section = Section.objects.get(pk=section_id)
        translation = SectionTranslation.objects.create(
            section=section,
            language=input.language,
            title=input.title,
            description=input.description,
        )
        return translation

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_section_translation_id, 'update')
    def update_section_translation(
        self,
        info: Info,
        id: UUID,
        input: SectionTranslationInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SectionTranslationType:
        """Update a section translation"""
        translation = SectionTranslation.objects.select_related('section__survey').get(pk=id)

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
    @check_permission(_type_from_section_translation_id, 'update')
    def delete_section_translation(
        self,
        info: Info,
        id: UUID,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> OperationResult:
        """Delete a section translation"""
        translation = SectionTranslation.objects.get(pk=id)
        translation.delete()
        return OperationResult(success=True)

    # ==================== Question Translations ====================

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_question_id, 'update')
    def create_question_translation(
        self,
        info: Info,
        question_id: int,
        input: QuestionTranslationInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> QuestionTranslationType:
        """Create a translation for a question"""
        question = Question.objects.get(pk=question_id)
        translation = QuestionTranslation.objects.create(
            question=question,
            language=input.language,
            title=input.title,
            description=input.description,
        )
        return translation

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_question_translation_id, 'update')
    def update_question_translation(
        self,
        info: Info,
        id: UUID,
        input: QuestionTranslationInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> QuestionTranslationType:
        """Update a question translation"""
        translation = QuestionTranslation.objects.select_related('question__survey').get(pk=id)

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
    @check_permission(_type_from_question_translation_id, 'update')
    def delete_question_translation(
        self,
        info: Info,
        id: UUID,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> OperationResult:
        """Delete a question translation"""
        translation = QuestionTranslation.objects.get(pk=id)
        translation.delete()
        return OperationResult(success=True)

    # ==================== Answer Schema Option Translations ====================

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_option_id, 'update')
    def create_answer_schema_option_translation(
        self,
        info: Info,
        option_id: int,
        input: AnswerSchemaOptionTranslationInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> AnswerSchemaOptionTranslationType:
        """Create a translation for an answer schema option"""
        option = AnswerSchemaOption.objects.get(pk=option_id)
        translation = AnswerSchemaOptionTranslation.objects.create(
            option=option,
            language=input.language,
            text=input.text,
        )
        return translation

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_option_translation_id, 'update')
    def update_answer_schema_option_translation(
        self,
        info: Info,
        id: UUID,
        input: AnswerSchemaOptionTranslationInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> AnswerSchemaOptionTranslationType:
        """Update an answer schema option translation"""
        translation = AnswerSchemaOptionTranslation.objects.select_related('option__survey').get(pk=id)

        if input.language:
            translation.language = input.language
        if input.text is not None:
            translation.text = input.text

        translation.save()
        return translation

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_option_translation_id, 'update')
    def delete_answer_schema_option_translation(
        self,
        info: Info,
        id: UUID,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> OperationResult:
        """Delete an answer schema option translation"""
        translation = AnswerSchemaOptionTranslation.objects.get(pk=id)
        translation.delete()
        return OperationResult(success=True)

    # ==================== Survey Collection Translations ====================

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    def create_survey_collection_translation(
        self,
        info: Info,
        collection_id: int,
        input: SurveyCollectionTranslationInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SurveyCollectionTranslationType:
        """Create a translation for a survey collection"""
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
        """Update a survey collection translation"""
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
        """Delete a survey collection translation"""
        translation = SurveyCollectionTranslation.objects.get(pk=id)
        translation.delete()
        return OperationResult(success=True)
