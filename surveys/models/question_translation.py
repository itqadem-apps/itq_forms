from uuid import uuid4

from django.db import models

from .question import Question


class QuestionTranslation(models.Model):
    class Meta:
        db_table = "surveys_questiontranslation"
        constraints = [
            models.UniqueConstraint(fields=["question", "language"], name="uq_question_language"),
        ]
        indexes = [
            models.Index(fields=["question", "language"], name="ix_question_tr_question_lang"),
        ]

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="translations")
    language = models.CharField(max_length=10)
    title = models.CharField(max_length=255, null=True, blank=True)
    description = models.TextField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.question_id}:{self.language}"
