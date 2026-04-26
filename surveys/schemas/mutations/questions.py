import strawberry
import strawberry_django
from strawberry.types import Info
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.db import transaction
from typing import List
from datetime import timedelta

from app.auth_utils import with_django_user
from app.permissions import check_permission
from surveys.inputs import QuestionInput
from surveys.types import QuestionType
from surveys.models import (
    Survey,
    Section,
    Question,
    QuestionTranslation,
    AnswerSchema,
    AnswerSchemaOption,
    AnswerSchemaOptionTranslation,
)
from ..common import RequireAuth, OperationResult
from ..utils import input_to_dict


def _type_from_section_id(info, section_id, **kw):
    return Section.objects.select_related('survey').get(pk=section_id).survey.survey_type


def _type_from_question_id(info, id, **kw):
    return Question.objects.select_related('survey').get(pk=id).survey.survey_type


@strawberry.type
class QuestionMutations:
    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_section_id, 'update')
    def create_question(
        self,
        info: Info,
        section_id: int,
        input: QuestionInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> QuestionType:
        """Create a new question in a section"""
        section = Section.objects.select_related('survey').get(pk=section_id)

        data = input_to_dict(input, exclude=['answer_time', 'translations'])
        data['survey'] = section.survey
        data['section'] = section
        if input.answer_time is not strawberry.UNSET:
            try:
                parts = input.answer_time.split(':')
                if len(parts) == 3:
                    hours, minutes, seconds = map(int, parts)
                    data['answer_time'] = timedelta(hours=hours, minutes=minutes, seconds=seconds)
            except Exception:
                raise ValidationError(f"Invalid answer_time format: {input.answer_time}. Expected HH:MM:SS")

        question = Question.objects.create(**data)

        # Create translations
        if input.translations:
            for trans_input in input.translations:
                QuestionTranslation.objects.create(
                    question=question,
                    language=trans_input.language,
                    title=trans_input.title,
                    description=trans_input.description,
                )

        # Signal auto-creates AnswerSchema; update it based on question type
        question.update_answer_schema()

        return question

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_question_id, 'update')
    def update_question(
        self,
        info: Info,
        id: int,
        input: QuestionInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> QuestionType:
        """Update an existing question"""
        question = Question.objects.select_related('survey', 'section').get(pk=id)

        for field, value in input_to_dict(input, exclude=['answer_time', 'translations']).items():
            setattr(question, field, value)
        if input.answer_time is not strawberry.UNSET:
            try:
                parts = input.answer_time.split(':')
                if len(parts) == 3:
                    hours, minutes, seconds = map(int, parts)
                    question.answer_time = timedelta(hours=hours, minutes=minutes, seconds=seconds)
            except Exception:
                raise ValidationError(f"Invalid answer_time format: {input.answer_time}. Expected HH:MM:SS")

        question.save()

        # Update answer schema based on question type
        question.update_answer_schema()

        # Update translations if provided
        if input.translations:
            for trans_input in input.translations:
                QuestionTranslation.objects.update_or_create(
                    question=question,
                    language=trans_input.language,
                    defaults={
                        'title': trans_input.title,
                        'description': trans_input.description,
                    }
                )

        return question

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_question_id, 'update')
    def delete_question(
        self,
        info: Info,
        id: int,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> OperationResult:
        """Delete a question"""
        question = Question.objects.get(pk=id)
        question.delete()
        return OperationResult(success=True)

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_question_id, 'update')
    @transaction.atomic
    def duplicate_question(
        self,
        info: Info,
        id: int,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> QuestionType:
        """Duplicate a question with its answer schema and options"""
        original_question = Question.objects.select_related('survey', 'section').get(pk=id)

        # Duplicate question
        new_question = Question.objects.get(pk=original_question.pk)
        new_question.pk = None
        new_question.title = f"{original_question.title} (Copy)" if original_question.title else None
        new_question.save()

        # Duplicate translations
        for translation in QuestionTranslation.objects.filter(question=original_question):
            QuestionTranslation.objects.create(
                question=new_question,
                language=translation.language,
                title=f"{translation.title} (Copy)" if translation.title else None,
                description=translation.description,
            )

        # Duplicate answer schema and options
        if hasattr(original_question, 'answer_schema'):
            old_schema = original_question.answer_schema
            new_schema = AnswerSchema.objects.create(
                survey=new_question.survey,
                section=new_question.section,
                question=new_question,
                type=old_schema.type,
                with_file=old_schema.with_file,
                is_mcq=old_schema.is_mcq,
                is_grid=old_schema.is_grid,
            )

            # Duplicate options
            for option in old_schema.options.all():
                old_option_id = option.id
                option.pk = None
                option.survey = new_question.survey
                option.section = new_question.section
                option.question = new_question
                option.schema = new_schema
                option.save()

                # Duplicate option translations
                for trans in AnswerSchemaOptionTranslation.objects.filter(option_id=old_option_id):
                    AnswerSchemaOptionTranslation.objects.create(
                        option=option,
                        language=trans.language,
                        text=trans.text,
                    )

        return new_question

    @strawberry.mutation(permission_classes=[RequireAuth])
    @with_django_user
    @check_permission(_type_from_section_id, 'update')
    def reorder_questions(
        self,
        info: Info,
        section_id: int,
        question_ids: List[int],
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> List[QuestionType]:
        """Reorder questions in a section"""
        section = Section.objects.select_related('survey').get(pk=section_id)

        # Validate all question IDs belong to the section
        questions = Question.objects.filter(id__in=question_ids, section=section)
        if questions.count() != len(question_ids):
            raise ValueError("Some question IDs are invalid or don't belong to this section")

        # Update order
        question_map = {question.id: question for question in questions}
        for order, question_id in enumerate(question_ids, start=1):
            question = question_map.get(question_id)
            if question:
                question.order = order
                question.save(update_fields=['order'])

        return list(Question.objects.filter(section=section).order_by('order'))
