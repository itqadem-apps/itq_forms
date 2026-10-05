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
from surveys.inputs import QuestionInput, QuestionPlacementInput
from surveys.question_order import (
    assert_forward_only,
    flat_question_ids,
    live_survey_questions,
    renumber_questions,
    split_sections,
)
from surveys.types import QuestionType, SurveyType
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
from app.graphql_ids import as_pk


def _type_from_section_id(info, section_id, **kw):
    return Section.objects.select_related('survey').get(pk=section_id).survey.survey_type


def _type_from_question_id(info, id, **kw):
    return Question.objects.select_related('survey').get(pk=id).survey.survey_type


def _type_from_survey_id(info, survey_id, **kw):
    return Survey.objects.values_list('survey_type', flat=True).get(pk=survey_id)


def _positions(sequence):
    return {pk: i for i, pk in enumerate(sequence, start=1)}


def _placed_sequence(survey_id, live_sequence, section_of):
    """The whole survey's sequence for a reorder of its live questions: each question the author
    cannot see (soft-deleted, or under a soft-deleted section) follows the last live question of
    its own section, so it never splits a run; one with no such run goes at the end."""
    hidden = [pk for pk in flat_question_ids(Question.objects.filter(survey_id=survey_id)) if pk not in section_of]
    hidden_section = dict(Question.objects.filter(pk__in=hidden).values_list('id', 'section_id'))
    last_of = {section_of[pk]: pk for pk in live_sequence if section_of[pk] is not None}
    after: dict[int, list[int]] = {}
    tail = []
    for pk in hidden:
        anchor = last_of.get(hidden_section[pk])
        (after.setdefault(anchor, []) if anchor is not None else tail).append(pk)
    sequence = []
    for pk in live_sequence:
        sequence.append(pk)
        sequence.extend(after.get(pk, ()))
    return sequence + tail


@strawberry.type
class QuestionMutations:
    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_section_id, 'update')
    def create_question(
        self,
        info: Info,
        section_id: strawberry.ID,
        input: QuestionInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> QuestionType:
        """Create a new question in a section"""
        section_id = as_pk(section_id)
        section = Section.objects.select_related('survey').get(pk=section_id)

        # `order` is not the client's to write: `renumber_questions` places the question (`forms:AD-4`).
        data = input_to_dict(input, exclude=['answer_time', 'translations', 'order'])
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
        id: strawberry.ID,
        input: QuestionInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> QuestionType:
        """Update an existing question"""
        id = as_pk(id)
        question = Question.objects.select_related('survey', 'section').get(pk=id)

        # `order` is ignored: a question moves only through the reorder mutations (`forms:AD-4`).
        for field, value in input_to_dict(input, exclude=['answer_time', 'translations', 'order']).items():
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
        id: strawberry.ID,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> OperationResult:
        """Delete a question"""
        id = as_pk(id)
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
        id: strawberry.ID,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> QuestionType:
        """Duplicate a question with its answer schema and options"""
        id = as_pk(id)
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

        # Reshape the answer schema the post_save signal has already created for the
        # copy. Creating a second one here violates surveys_answerschema_question_id_key
        # -- AnswerSchema.question is a OneToOneField -- and every question has a schema,
        # so that path was taken every time and duplication never worked at all.
        old_schema = getattr(original_question, 'answer_schema', None)
        new_schema = AnswerSchema.objects.filter(question=new_question).first()
        if old_schema and new_schema:
            new_schema.type = old_schema.type
            new_schema.with_file = old_schema.with_file
            new_schema.is_mcq = old_schema.is_mcq
            new_schema.is_grid = old_schema.is_grid
            new_schema.save()

            # The signal seeds a blank option (or one per classification). Those belong
            # to a question being created, not to a copy, which takes the original's.
            new_schema.options.all().delete()

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
    @transaction.atomic
    def reorder_questions(
        self,
        info: Info,
        section_id: strawberry.ID,
        question_ids: List[int],
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> List[QuestionType]:
        """Reorder questions within a section, which stays where it is in the survey. Questions of
        the section left out of `question_ids` follow the listed ones in their current order."""
        section_id = as_pk(section_id)
        section = Section.objects.select_related('survey').get(pk=section_id)
        survey = Survey.objects.select_for_update().get(pk=section.survey_id)

        # Validate all question IDs belong to the section
        questions = Question.objects.filter(id__in=question_ids, section=section)
        if questions.count() != len(question_ids):
            raise ValueError("Some question IDs are invalid or don't belong to this section")

        current = flat_question_ids(Question.objects.filter(survey_id=survey.id))
        members = set(Question.objects.filter(section=section).values_list('id', flat=True))
        listed = set(question_ids)
        run = iter(list(question_ids) + [pk for pk in current if pk in members and pk not in listed])
        sequence = [next(run) if pk in members else pk for pk in current]

        assert_forward_only(survey, _positions(sequence), field='question_ids')
        renumber_questions(survey.id, sequence)

        return list(Question.objects.filter(section=section).order_by('order'))

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_survey_id, 'update')
    @transaction.atomic
    def reorder_survey_questions(
        self,
        info: Info,
        survey_id: strawberry.ID,
        placements: List[QuestionPlacementInput],
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SurveyType:
        """Lay out every live question of a survey in one survey-wide order (`forms:AD-4`).

        `placements` lists each live question exactly once, in its new order, naming the section
        it ends up in (or null for none) — a question listed under another section moves there.
        A layout that leaves any section's questions non-contiguous is refused on `placements`.
        """
        survey_id = as_pk(survey_id)
        survey = Survey.objects.select_for_update().get(pk=survey_id)

        live = dict(live_survey_questions(survey.id).values_list('id', 'section_id'))
        sections = dict(
            Section.objects.filter(survey=survey, deleted_at__isnull=True).values_list('id', 'title')
        )

        if any(p.section_id is strawberry.UNSET for p in placements):
            raise ValidationError({'placements': 'Every placement must name its section, or null for none.'})
        live_sequence = [as_pk(p.question_id) for p in placements]
        if len(live_sequence) != len(live) or set(live_sequence) != set(live):
            raise ValidationError({'placements': 'Placements must list every question of the survey exactly once.'})

        section_of = {as_pk(p.question_id): as_pk(p.section_id) for p in placements}
        errors = []
        for pk, sid in section_of.items():
            if sid is not None and sid not in sections:
                errors.append(f"Section {sid} is not a section of this survey.")
            elif sid is None and live[pk] is not None:
                # Until sections are optional end to end, a question's answer schema needs one.
                errors.append(f"Question {pk} cannot leave its section yet.")
        split = split_sections(live_sequence, section_of)
        errors += [
            f"The questions of section \"{sections.get(sid) or sid}\" must sit together, with nothing between them."
            for sid in split
        ]
        if errors:
            raise ValidationError({'placements': errors})

        sequence = _placed_sequence(survey.id, live_sequence, section_of)
        assert_forward_only(survey, _positions(sequence), field='placements')

        moved = {pk: sid for pk, sid in section_of.items() if live[pk] != sid}
        for sid in set(moved.values()):
            ids = [pk for pk, dest in moved.items() if dest == sid]
            Question.objects.filter(pk__in=ids).update(section_id=sid)
            AnswerSchema.objects.filter(question_id__in=ids).update(section_id=sid)
            AnswerSchemaOption.objects.filter(question_id__in=ids).update(section_id=sid)
        renumber_questions(survey.id, sequence)

        return survey
