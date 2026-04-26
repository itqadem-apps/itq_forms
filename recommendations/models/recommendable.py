from django.db import models
from django.utils.timezone import now


class Recommendable(models.Model):
    source_service = models.CharField(max_length=255)
    source_model = models.CharField(max_length=255)
    source_id = models.CharField(max_length=255)
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=now, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_service", "source_model", "source_id"],
                name="uq_recommendable_source",
            ),
        ]

    def __str__(self):
        return f"{self.source_service}:{self.source_model}:{self.source_id}"
