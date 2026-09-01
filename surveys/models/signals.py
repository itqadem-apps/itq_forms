from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .answer_schema import AnswerSchema
from .answer_schema_option import AnswerSchemaOption
from .question import Question
from .section import Section


@receiver(post_save, sender=Section)
def _create_section_first_question(sender, instance: Section, created: bool, **kwargs):
    if created:
        instance.questions.create(survey_id=instance.survey_id)


@receiver(post_save, sender=Question)
def _create_answer_schema_for_new_question(sender, instance: Question, created: bool, **kwargs):
    if created:
        AnswerSchema.objects.create(
            survey_id=instance.survey_id,
            section_id=instance.section_id,
            type=instance.type,
            question=instance,
            with_file=instance.type in [instance.QUESTION_TYPE_RADIO_MCQ, instance.QUESTION_TYPE_CHECKBOX_MCQ],
            is_mcq=instance.type
            in [
                instance.QUESTION_TYPE_RADIO_MCQ,
                instance.QUESTION_TYPE_CHECKBOX_MCQ,
                instance.QUESTION_TYPE_DROPDOWN_MCQ,
            ],
            is_grid=instance.type in [instance.QUESTION_TYPE_RADIO_GRID, instance.QUESTION_TYPE_CHECKBOX_GRID],
        )


@receiver(post_save, sender=AnswerSchema)
def _create_answer_schema_first_option(sender, instance: AnswerSchema, created: bool, **kwargs):
    if not created:
        return

    if instance.type in [
        Question.QUESTION_TYPE_RADIO_MCQ,
        Question.QUESTION_TYPE_CHECKBOX_MCQ,
        Question.QUESTION_TYPE_DROPDOWN_MCQ,
    ]:
        survey = instance.survey
        if survey.use_classifications and survey.create_option_for_each_classification:
            for classification in survey.classifications.all():
                instance.options.create(
                    text=classification.name or "",
                    score=classification.score if survey.use_score else None,
                    classification=classification,
                    survey_id=instance.survey_id,
                    section_id=instance.section_id,
                    question_id=instance.question_id,
                )
        else:
            instance.options.create(
                survey_id=instance.survey_id,
                section_id=instance.section_id,
                question_id=instance.question_id,
            )
        return

    if instance.type in [Question.QUESTION_TYPE_RADIO_GRID, Question.QUESTION_TYPE_CHECKBOX_GRID]:
        instance.options.create(
            survey_id=instance.survey_id,
            section_id=instance.section_id,
            question_id=instance.question_id,
            is_column=False,
            is_row=True,
        )
        instance.options.create(
            survey_id=instance.survey_id,
            section_id=instance.section_id,
            question_id=instance.question_id,
            is_column=True,
            is_row=False,
        )


@receiver(post_save, sender=Section)
@receiver(post_delete, sender=Section)
def _update_sections_order(sender, instance: Section, **kwargs):
    sections = Section.objects.filter(survey_id=instance.survey_id).order_by("order", "id")
    sections_order = list(sections.values_list("order", flat=True))

    if all(order == idx + 1 for idx, order in enumerate(sections_order)):
        return

    for idx, section in enumerate(sections):
        section.order = idx + 1
    Section.objects.bulk_update(sections, ["order"])


@receiver(post_save, sender=Question)
@receiver(post_delete, sender=Question)
def _update_question_order(sender, instance: Question, **kwargs):
    questions = Question.objects.filter(section_id=instance.section_id).order_by("order", "id")
    questions_order = list(questions.values_list("order", flat=True))

    if all(order == idx + 1 for idx, order in enumerate(questions_order)):
        return

    for idx, question in enumerate(questions):
        question.order = idx + 1
    Question.objects.bulk_update(questions, ["order"])


@receiver(post_save, sender=AnswerSchemaOption)
@receiver(post_delete, sender=AnswerSchemaOption)
def _update_answer_schema_option_order(sender, instance: AnswerSchemaOption, **kwargs):
    """Keep option order contiguous, the way sections and questions already are.

    Options were the one level of the tree without this. Deleting the third of
    four left the survey holding 1, 2, 4 for good — a hole a respondent sees as
    a missing choice, and one that no amount of re-reading the template
    explains, because nothing in the authoring UI can produce it. Worse,
    ``AnswerSchemaOption.save`` assigns a new option ``schema.options.count() +
    1``, so the next option added to that schema is also given 4 and ties with
    the survivor under ``Meta.ordering``.

    Both follow from the same absence, so both are fixed here rather than in
    ``save``: resequencing after a delete keeps ``count() + 1`` correct by
    construction.
    """
    options = AnswerSchemaOption.objects.filter(schema_id=instance.schema_id).order_by("order", "id")
    options_order = list(options.values_list("order", flat=True))

    if all(order == idx + 1 for idx, order in enumerate(options_order)):
        return

    for idx, option in enumerate(options):
        option.order = idx + 1
    AnswerSchemaOption.objects.bulk_update(options, ["order"])
