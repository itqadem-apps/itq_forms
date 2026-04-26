from uuid import uuid4

from django.db import models

from .answer_schema_option import AnswerSchemaOption


class AnswerSchemaOptionTranslation(models.Model):
    class Meta:
        db_table = "surveys_answerschemaoptiontranslation"
        constraints = [
            models.UniqueConstraint(fields=["option", "language"], name="uq_answer_schema_option_language"),
        ]
        indexes = [
            models.Index(fields=["option", "language"], name="ix_ans_opt_tr_lang"),
        ]

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    option = models.ForeignKey(AnswerSchemaOption, on_delete=models.CASCADE, related_name="translations")
    language = models.CharField(max_length=10)
    text = models.TextField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.option_id}:{self.language}"
