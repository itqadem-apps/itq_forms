from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.timezone import now


class ExternalReference(models.Model):
    source_service = models.CharField(max_length=255)
    source_model = models.CharField(max_length=255)
    source_id = models.CharField(max_length=255)
    collection = models.ForeignKey(
        "survey_collections.SurveyCollection",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="external_references",
    )
    survey = models.ForeignKey(
        "surveys.Survey",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="external_references",
    )
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=now, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(collection__isnull=False) | Q(survey__isnull=False),
                name="external_ref_has_local_target",
            ),
            models.UniqueConstraint(
                fields=["source_service", "source_model", "source_id", "collection", "survey"],
                name="uq_external_ref_source_target",
                nulls_distinct=False,
            ),
        ]
        indexes = [
            models.Index(
                fields=["source_service", "source_model", "source_id"],
                name="ix_ext_ref_source",
            ),
        ]

    def clean(self):
        if self.collection_id is None and self.survey_id is None:
            raise ValidationError("External reference requires collection or survey.")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.source_service}:{self.source_model}:{self.source_id}"
