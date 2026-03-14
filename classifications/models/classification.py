from django.db import models
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _

from surveys.models.has_soft_delete import HasSoftDelete


class Classification(HasSoftDelete):
    class Meta:
        ordering = ["created_at"]
        verbose_name = _("Classification")
        verbose_name_plural = _("Classifications")

    survey = models.ForeignKey("surveys.Survey", on_delete=models.CASCADE, related_name="classifications", null=True, blank=True)
    score = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_created=True, default=now, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    @property
    def name(self):
        """Convenience accessor: returns the name from the first translation."""
        t = self.translations.first()
        return t.name if t else None

    def __str__(self):
        return self.name or str(self.pk)
