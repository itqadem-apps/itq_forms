from uuid import uuid4

from django.db import models

from .classification import Classification


class ClassificationTranslation(models.Model):
    class Meta:
        db_table = "surveys_classificationtranslation"
        constraints = [
            models.UniqueConstraint(fields=["classification", "language"], name="uq_classification_language"),
        ]
        indexes = [
            models.Index(fields=["classification", "language"], name="ix_class_tr_lang"),
        ]

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    classification = models.ForeignKey(Classification, on_delete=models.CASCADE, related_name="translations")
    language = models.CharField(max_length=10)
    name = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.classification_id}:{self.language}"
