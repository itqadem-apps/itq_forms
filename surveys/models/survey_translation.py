from uuid import uuid4

from django.db import models

from .survey import Survey


class SurveyTranslation(models.Model):
    class Meta:
        db_table = "surveys_surveytranslation"
        constraints = [
            models.UniqueConstraint(fields=["survey", "language"], name="uq_survey_language"),
        ]
        indexes = [
            models.Index(fields=["survey", "language"], name="ix_survey_tr_survey_lang"),
        ]

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name="translations")
    language = models.CharField(max_length=10)
    title = models.CharField(max_length=255, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    short_description = models.CharField(max_length=300, null=True, blank=True)
    slug = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.survey_id}:{self.language}"
