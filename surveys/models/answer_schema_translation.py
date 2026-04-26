from uuid import uuid4

from django.db import models

from .answer_schema import AnswerSchema


class AnswerSchemaTranslation(models.Model):
    class Meta:
        db_table = "surveys_answerschematranslation"
        constraints = [
            models.UniqueConstraint(fields=["schema", "language"], name="uq_answer_schema_language"),
        ]
        indexes = [
            models.Index(fields=["schema", "language"], name="ix_ans_schema_tr_lang"),
        ]

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    schema = models.ForeignKey(AnswerSchema, on_delete=models.CASCADE, related_name="translations")
    language = models.CharField(max_length=10)
    def __str__(self) -> str:
        return f"{self.schema_id}:{self.language}"
