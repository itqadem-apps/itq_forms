from django.db import models

from .question import Question
from .section import Section
from .survey import Survey


class AnswerSchema(models.Model):
    survey = models.ForeignKey(Survey, on_delete=models.CASCADE)
    # Nullable for a sectionless question (`forms:AD-9`), and SET_NULL so removing a section can
    # never cascade away the schema of a question that no longer sits in it.
    section = models.ForeignKey(Section, on_delete=models.SET_NULL, null=True, blank=True)
    question = models.OneToOneField(Question, on_delete=models.CASCADE, related_name="answer_schema")
    type = models.CharField(max_length=100, choices=Question.QUESTION_TYPE_CHOICES, default=Question.QUESTION_TYPE_RADIO_MCQ)
    with_file = models.BooleanField(default=False)
    is_mcq = models.BooleanField(default=False)
    is_grid = models.BooleanField(default=False)
