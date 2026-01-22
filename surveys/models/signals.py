from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .answer_schema import AnswerSchema
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
                    text=classification.name,
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
