import strawberry
import strawberry_django
from strawberry.types import Info
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.db import transaction
from typing import List, Optional
from datetime import timedelta

from app.auth_utils import with_django_user
from app.permissions import check_permission, require_permission
from app.platform import ensure_in_org
from surveys.card_anchor import anchor_of, anchor_survey_id, check_live, layout
from surveys.flow import check_type_change
from surveys.inputs import CardAnchorInput, QuestionInput, QuestionPlacementInput
from surveys.question_copy import copy_question
from surveys.question_order import (
    assert_forward_only,
    flat_question_ids,
    insert_after,
    live_survey_questions,
    move_to_section,
    renumber_questions,
    split_sections,
)
from surveys.soft_delete import soft_delete
from surveys.survey_lock import lock_survey, lock_survey_of_question, lock_survey_of_section
from surveys.types import QuestionType, SurveyType
from surveys.models import (
    Survey,
    Section,
    Question,
    QuestionTranslation,
)
from ..common import RequireAuth, OperationResult
from ..utils import input_to_dict
from app.graphql_ids import as_pk


def _type_from_section_id(info, section_id, **kw):
    return Section.objects.select_related('survey').get(pk=section_id).survey.survey_type


def _type_for_new_question(info, section_id=None, survey_id=None, after=None, **kw):
    if after is not None:
        return _type_from_anchor(info, after)
    if section_id is not None:
        return _type_from_section_id(info, section_id)
    return _type_from_survey_id(info, survey_id)


def _type_from_question_id(info, id, **kw):
    # `all_objects`: a deleted question is refused by the resolver on `id`, not as a lookup miss here.
    return Question.all_objects.select_related('survey').get(pk=id).survey.survey_type


def _type_from_survey_id(info, survey_id, **kw):
    return Survey.objects.values_list('survey_type', flat=True).get(pk=survey_id)


def _type_from_anchor(info, after, **kw):
    return _type_from_survey_id(info, anchor_survey_id(anchor_of(after)))


def _positions(sequence):
    return {pk: i for i, pk in enumerate(sequence, start=1)}


def _placed_sequence(survey_id, live_sequence, section_of):
    """The survey's live sequence for a reorder (`renumber_questions` takes live questions only,
    `forms:AD-21`): each live question the author cannot see — one still under a soft-deleted
    section, which the soft-delete backfill leaves none of — follows the last listed question of
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
    @check_permission(_type_for_new_question, 'update')
    @transaction.atomic
    def create_question(
        self,
        info: Info,
        input: QuestionInput,
        section_id: Optional[strawberry.ID] = None,
        survey_id: Optional[strawberry.ID] = None,
        after: Optional[CardAnchorInput] = None,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> QuestionType:
        """Create a question right after the card `after` names, in that card's section
        (`forms:AD-24`); or, without `after`, at the end of a section, or — given `surveyId` and no
        `sectionId` — a sectionless one at the end of the survey (`forms:AD-9`)."""
        section_id, survey_id = as_pk(section_id), as_pk(survey_id)
        anchor = anchor_of(after) if after is not None else None
        if anchor is not None:
            survey_id_locked = lock_survey(anchor_survey_id(anchor))
            sequence, section_of = layout(survey_id_locked)
            check_live(anchor, survey_id_locked, sequence)
            _, anchor_section_id = insert_after(sequence, section_of, anchor, [])
            if (survey_id is not None and survey_id != survey_id_locked) or (
                section_id is not None and section_id != anchor_section_id
            ):
                raise ValidationError({'after': 'The card this follows is not in the named survey or section.'})
            survey = Survey.objects.get(pk=survey_id_locked)
            ensure_in_org(survey, info.context.auth_context)
            section = Section.objects.get(pk=anchor_section_id) if anchor_section_id is not None else None
        elif section_id is not None:
            lock_survey_of_section(section_id)
            section = Section.objects.select_related('survey').get(pk=section_id)
            if survey_id is not None and survey_id != section.survey_id:
                raise ValidationError({'survey_id': 'The section is not in this survey.'})
            survey = section.survey
        elif survey_id is not None:
            lock_survey(survey_id)
            section = None
            survey = Survey.objects.get(pk=survey_id)
        else:
            raise ValidationError({'section_id': 'Name the section, or the survey for a question with no section.'})

        # `order` is not the client's to write: `renumber_questions` places the question (`forms:AD-4`).
        data = input_to_dict(input, exclude=['answer_time', 'translations', 'order'])
        data['survey'] = survey
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

        if anchor is not None:
            renumber_questions(survey.id, insert_after(sequence, section_of, anchor, [question.pk])[0])
            question.refresh_from_db(fields=['order'])
        return question

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_question_id, 'update')
    @transaction.atomic
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
        if input.type is not strawberry.UNSET and input.type != question.type:
            Survey.objects.select_for_update().filter(pk=question.survey_id).first()
            check_type_change(question.pk, input.type)

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
    @transaction.atomic
    def delete_question(
        self,
        info: Info,
        id: strawberry.ID,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> OperationResult:
        """Soft-delete a question and its options (`forms:AD-21`). Refused on `target_id` while a
        live option of another question jumps to it (`forms:AD-22`)."""
        id = as_pk(id)
        survey_id = lock_survey_of_question(id)
        soft_delete('question', Question.objects.get(pk=id), survey_id)
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
        """Copy a question right after itself, in its section, through `copy_question`
        (`forms:AD-24`)."""
        id = as_pk(id)
        owner = Question.all_objects.filter(pk=id).values_list('survey_id', 'section__survey_id').first()
        if owner is None or not any(owner):
            raise ValidationError({'id': 'The question no longer exists or belongs to no survey.'})
        survey_id = lock_survey(owner[0] or owner[1])
        sequence, section_of = layout(survey_id)
        if id not in section_of:
            raise ValidationError({'id': 'The question was deleted; reload the survey.'})
        original = Question.objects.select_related('section').get(pk=id)
        copy = copy_question(original, Survey.objects.get(pk=survey_id), original.section, as_duplicate=True)
        renumber_questions(survey_id, insert_after(sequence, section_of, ('question', original.pk), [copy.pk])[0])
        copy.refresh_from_db(fields=['order'])
        return copy

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_anchor, 'update')
    @transaction.atomic
    def import_question(
        self,
        info: Info,
        source_question_id: strawberry.ID,
        after: CardAnchorInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> QuestionType:
        """Insert an independent copy of a question from any survey the caller can read right
        after the card `after` names, in that card's section (`forms:AD-24`). Needs read on the
        source survey and update on the target; nothing links the copy to its source."""
        anchor = anchor_of(after)
        survey_id = lock_survey(anchor_survey_id(anchor))
        auth_ctx = info.context.auth_context
        target = Survey.objects.get(pk=survey_id)
        ensure_in_org(target, auth_ctx)

        source = Question.all_objects.select_related('section').filter(pk=as_pk(source_question_id)).first()
        source_survey_id = source and (source.survey_id or (source.section.survey_id if source.section_id else None))
        if source_survey_id is None:
            raise ValidationError({'source_question_id': 'The question to import does not exist or belongs to no survey.'})
        source_survey = Survey.objects.get(pk=source_survey_id)
        # Organization and key before liveness, so a foreign row reads the same deleted or not.
        ensure_in_org(source_survey, auth_ctx)
        require_permission(auth_ctx, source_survey.survey_type, 'read')
        if source.deleted_at or (source.section_id and source.section.deleted_at) or source_survey.deleted_at:
            raise ValidationError({'source_question_id': 'The question to import no longer exists.'})

        sequence, section_of = layout(survey_id)
        check_live(anchor, survey_id, sequence)
        _, section_id = insert_after(sequence, section_of, anchor, [])
        section = Section.objects.get(pk=section_id) if section_id is not None else None
        copy = copy_question(source, target, section, as_duplicate=False)
        renumber_questions(survey_id, insert_after(sequence, section_of, anchor, [copy.pk])[0])
        copy.refresh_from_db(fields=['order'])
        return copy

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
            move_to_section([pk for pk, dest in moved.items() if dest == sid], sid)
        renumber_questions(survey.id, sequence)

        return survey
