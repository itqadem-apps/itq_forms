from uuid import uuid4

from django.db import models

from .recommendation import Recommendation


class RecommendationTranslation(models.Model):
    class Meta:
        db_table = "surveys_recommendationtranslation"
        constraints = [
            models.UniqueConstraint(fields=["recommendation", "language"], name="uq_recommendation_language"),
        ]
        indexes = [
            models.Index(fields=["recommendation", "language"], name="ix_recommendation_tr_rec_lang"),
        ]

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    recommendation = models.ForeignKey(Recommendation, on_delete=models.CASCADE, related_name="translations")
    language = models.CharField(max_length=10)
    description = models.TextField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.recommendation_id}:{self.language}"
