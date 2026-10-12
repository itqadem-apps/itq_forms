"""The one copy of a question, for Duplicate and Import alike (`forms:AD-24`).

The copy is independent: nothing links it to its source. It takes the question, its answer
schema, its live options and every translation of the three. Every edge falls through, because
the source's edges led on from the source. Across surveys the copy also drops what belongs to the
source survey: each option's classification and ending flag, and every image — a shared asset id
would let one survey's visibility change revoke the other's access (`media_access`). Score is
kept (an assumption the spine carries).

Placement is the caller's: the copy is created unplaced, and the caller runs `renumber_questions`
with the sequence it wants.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.utils.timezone import now

from surveys.models import (
    AnswerSchema,
    AnswerSchemaOptionTranslation,
    AnswerSchemaTranslation,
    FlowAction,
    Question,
    QuestionTranslation,
    Section,
    Survey,
)
from surveys.schemas.utils import clone_instance


_SUFFIX = " (Copy)"


def _copied(title, as_duplicate, model):
    """`title` marked as a copy, the base cut so the whole fits `model.title`."""
    if not (as_duplicate and title):
        return title
    return title[: model._meta.get_field("title").max_length - len(_SUFFIX)] + _SUFFIX


def copy_question(source: Question, target_survey: Survey, section: Section | None, *, as_duplicate: bool) -> Question:
    if source.survey_id is None and source.section_id is None:
        raise ValidationError({"id": "The question belongs to no survey."})
    source_survey_id = source.survey_id or Section.all_objects.values_list("survey_id", flat=True).get(pk=source.section_id)
    across = source_survey_id != target_survey.pk

    copy = clone_instance(
        source,
        survey=target_survey,
        section=section,
        order=None,
        deleted_at=None,
        created_at=now(),
        title=_copied(source.title, as_duplicate, Question),
        cover_asset_id=None if across else source.cover_asset_id,
    )
    for t in QuestionTranslation.objects.filter(question=source):
        clone_instance(t, question=copy, title=_copied(t.title, as_duplicate, QuestionTranslation))

    old_schema = AnswerSchema.objects.filter(question=source).first()
    # The post_save signal has already given the copy a schema (one-to-one), shaped by its type.
    new_schema = AnswerSchema.objects.filter(question=copy).first()
    if old_schema is None or new_schema is None:
        return copy
    new_schema.type = old_schema.type
    new_schema.with_file = old_schema.with_file
    new_schema.is_mcq = old_schema.is_mcq
    new_schema.is_grid = old_schema.is_grid
    new_schema.section = section
    new_schema.save()
    for t in AnswerSchemaTranslation.objects.filter(schema=old_schema):
        clone_instance(t, schema=new_schema)

    # The seeded options belong to a question being created, not to a copy (`forms:AD-21`).
    new_schema.options.all().delete()
    for option in old_schema.options.all():
        new_option = clone_instance(
            option,
            survey=target_survey,
            section=section,
            question=copy,
            schema=new_schema,
            deleted_at=None,
            flow_action=FlowAction.FALL_THROUGH,
            flow_target=None,
            classification=None if across else option.classification,
            ending_option=None if across else option.ending_option,
            image_asset_id=None if across else option.image_asset_id,
        )
        for t in AnswerSchemaOptionTranslation.objects.filter(option=option):
            clone_instance(t, option=new_option)
    return copy
