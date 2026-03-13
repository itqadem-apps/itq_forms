from django.db import models
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _

from surveys.models.has_soft_delete import HasSoftDelete


class Classification(HasSoftDelete):
    class Meta:
        ordering = ["created_at"]
        verbose_name = _("Classification")
        verbose_name_plural = _("Classifications")
        db_table = "surveys_classification"

    name = models.CharField(max_length=255, null=True, blank=True)
    survey = models.ForeignKey("surveys.Survey", on_delete=models.CASCADE, related_name="classifications", null=True, blank=True)
    score = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_created=True, default=now, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    def __str__(self):
        return self.name or ""
