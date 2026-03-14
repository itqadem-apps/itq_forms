from django.db import models
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _

from surveys.models.has_soft_delete import HasSoftDelete


class Recommendation(HasSoftDelete):
    class Meta:
        ordering = ["created_at"]
        verbose_name = _("Recommendation")
        verbose_name_plural = _("Recommendations")

    description = models.TextField()
    survey = models.ForeignKey("surveys.Survey", on_delete=models.CASCADE, related_name="recommendations", null=True, blank=True)
    option = models.ForeignKey(
        "surveys.AnswerSchemaOption",
        on_delete=models.CASCADE,
        related_name="option_recommendations",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_created=True, default=now, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    def __str__(self):
        return self.description
