import strawberry
import strawberry_django
from strawberry.types import Info
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.db import transaction
from typing import List

from app.auth_utils import with_django_user
from app.permissions import check_permission
from surveys.inputs import SectionInput
from surveys.types import SectionType
from surveys.models import Survey, Section, SectionTranslation, Question
from surveys.question_order import assert_forward_only, flat_question_ids, renumber_questions
from ..common import RequireAuth, OperationResult
from ..utils import input_to_dict
from app.graphql_ids import as_pk


def _type_from_survey_id(info, survey_id, **kw):
    return Survey.objects.values_list('survey_type', flat=True).get(pk=survey_id)


def _type_from_section_id(info, id, **kw):
    return Section.objects.select_related('survey').get(pk=id).survey.survey_type


def _refuse_legacy_jump(input: SectionInput) -> None:
    """forms:AD-15: the solver does not honour a section jump, so it must not be
    authorable. The columns stay; only the API refuses a value for them."""
    errors = {}
    if input.submit_action == Section.SUBMIT_ACTION_JUMP:
        errors['submit_action'] = 'Section jumps are no longer supported; use question-level flow instead.'
    if input.submit_action_target_id not in (strawberry.UNSET, None):
        errors['submit_action_target'] = 'Section jump targets are no longer supported and must be null.'
    if errors:
        raise ValidationError(errors)


@strawberry.type
class SectionMutations:
    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_survey_id, 'update')
    def create_section(
        self,
        info: Info,
        survey_id: strawberry.ID,
        input: SectionInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SectionType:
        """Create a new section in a survey"""
        _refuse_legacy_jump(input)
        survey_id = as_pk(survey_id)
        survey = Survey.objects.get(pk=survey_id)

        # `is_hidden` is not authorable (`forms:AD-9`); it is ignored, not refused, because the
        # admin's duplicate-section flow still sends the source section's value.
        data = input_to_dict(input, exclude=['submit_action_target_id', 'translations', 'is_hidden'])
        data['survey'] = survey

        section = Section.objects.create(**data)

        # Create translations
        if input.translations:
            for trans_input in input.translations:
                SectionTranslation.objects.create(
                    section=section,
                    language=trans_input.language,
                    title=trans_input.title,
                    description=trans_input.description,
                )

        return section

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_section_id, 'update')
    def update_section(
        self,
        info: Info,
        id: strawberry.ID,
        input: SectionInput,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> SectionType:
        """Update an existing section"""
        _refuse_legacy_jump(input)
        id = as_pk(id)
        section = Section.objects.select_related('survey').get(pk=id)

        # `order` is ignored: a section is placed by its first question, and moves only through
        # `reorder_sections` (`forms:AD-4`).
        # `is_hidden` is ignored for the same reason as in `create_section` (`forms:AD-9`).
        for field, value in input_to_dict(input, exclude=['submit_action_target_id', 'translations', 'order', 'is_hidden']).items():
            setattr(section, field, value)
        if input.submit_action_target_id is None:
            section.submit_action_target = None

        section.save()

        # Update translations if provided
        if input.translations:
            for trans_input in input.translations:
                SectionTranslation.objects.update_or_create(
                    section=section,
                    language=trans_input.language,
                    defaults={
                        'title': trans_input.title,
                        'description': trans_input.description,
                    }
                )

        return section

    @strawberry_django.mutation(permission_classes=[RequireAuth], handle_django_errors=True)
    @with_django_user
    @check_permission(_type_from_section_id, 'update')
    def delete_section(
        self,
        info: Info,
        id: strawberry.ID,
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> OperationResult:
        """Delete a section"""
        id = as_pk(id)
        section = Section.objects.get(pk=id)
        section.delete()
        return OperationResult(success=True)

    @strawberry.mutation(permission_classes=[RequireAuth])
    @with_django_user
    @check_permission(_type_from_survey_id, 'update')
    @transaction.atomic
    def reorder_sections(
        self,
        info: Info,
        survey_id: strawberry.ID,
        section_ids: List[int],
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> List[SectionType]:
        """Reorder sections in a survey. Each section's questions move with it; a sectionless
        question keeps its place between sections. Sections left out follow the listed ones."""
        survey_id = as_pk(survey_id)
        survey = Survey.objects.select_for_update().get(pk=survey_id)

        # Validate all section IDs belong to the survey
        sections = Section.objects.filter(id__in=section_ids, survey=survey)
        if sections.count() != len(section_ids):
            raise ValueError("Some section IDs are invalid or don't belong to this survey")

        listed = set(section_ids)
        rank = list(section_ids) + [
            sid for sid in Section.objects.filter(survey=survey).order_by('order', 'id').values_list('id', flat=True)
            if sid not in listed
        ]

        # The survey as units — a section's questions together, or one sectionless question — so
        # the sections can be permuted among the slots they hold without touching the rest.
        current = flat_question_ids(Question.objects.filter(survey_id=survey.id))
        section_of = dict(Question.objects.filter(survey_id=survey.id).values_list('id', 'section_id'))
        blocks: dict[int, list[int]] = {}
        units: list = []
        for pk in current:
            sid = section_of[pk]
            if sid is None:
                units.append(pk)
            elif sid not in blocks:
                blocks[sid] = [pk]
                units.append(None)
            else:
                blocks[sid].append(pk)
        ranked = set(rank)
        moving = iter([sid for sid in rank if sid in blocks] + [sid for sid in blocks if sid not in ranked])
        sequence = []
        for unit in units:
            sequence.extend(blocks[next(moving)] if unit is None else [unit])

        assert_forward_only(survey, {pk: i for i, pk in enumerate(sequence, start=1)}, field='section_ids')
        renumber_questions(survey.id, sequence, section_rank=rank)

        return list(Section.objects.filter(survey=survey).order_by('order'))
