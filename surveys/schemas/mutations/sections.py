import strawberry
import strawberry_django
from strawberry.types import Info
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ValidationError
from typing import List

from app.auth_utils import with_django_user
from app.permissions import check_permission
from surveys.inputs import SectionInput
from surveys.types import SectionType
from surveys.models import Survey, Section, SectionTranslation
from ..common import RequireAuth, OperationResult
from ..utils import input_to_dict
from app.graphql_ids import as_pk


def _type_from_survey_id(info, survey_id, **kw):
    return Survey.objects.values_list('survey_type', flat=True).get(pk=survey_id)


def _type_from_section_id(info, id, **kw):
    return Section.objects.select_related('survey').get(pk=id).survey.survey_type


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
        survey_id = as_pk(survey_id)
        survey = Survey.objects.get(pk=survey_id)

        data = input_to_dict(input, exclude=['submit_action_target_id', 'translations'])
        data['survey'] = survey
        if input.submit_action_target_id is not strawberry.UNSET:
            data['submit_action_target'] = Section.objects.get(pk=input.submit_action_target_id, survey=survey)

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
        id = as_pk(id)
        section = Section.objects.select_related('survey').get(pk=id)

        for field, value in input_to_dict(input, exclude=['submit_action_target_id', 'translations']).items():
            setattr(section, field, value)
        if input.submit_action_target_id is not strawberry.UNSET:
            section.submit_action_target = Section.objects.get(pk=input.submit_action_target_id, survey=section.survey)

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
    def reorder_sections(
        self,
        info: Info,
        survey_id: strawberry.ID,
        section_ids: List[int],
        django_user: strawberry.Private[AbstractBaseUser] = None,
    ) -> List[SectionType]:
        """Reorder sections in a survey"""
        survey_id = as_pk(survey_id)
        survey = Survey.objects.get(pk=survey_id)

        # Validate all section IDs belong to the survey
        sections = Section.objects.filter(id__in=section_ids, survey=survey)
        if sections.count() != len(section_ids):
            raise ValueError("Some section IDs are invalid or don't belong to this survey")

        # Update order
        section_map = {section.id: section for section in sections}
        for order, section_id in enumerate(section_ids, start=1):
            section = section_map.get(section_id)
            if section:
                section.order = order
                section.save(update_fields=['order'])

        return list(Section.objects.filter(survey=survey).order_by('order'))
