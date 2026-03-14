from django.db import models
from django.utils.translation import gettext_lazy as _


class Action(models.Model):
    class Meta:
        ordering = ["id"]

    survey = models.ForeignKey("surveys.Survey", on_delete=models.CASCADE, related_name="actions")
    upper_limit = models.FloatField(default=0, verbose_name=_("Upper Limit"))
    lower_limit = models.FloatField(default=0, verbose_name=_("Lower Limit"))

    @property
    def title(self):
        t = self.translations.first()
        return t.title if t else None

    @property
    def description(self):
        t = self.translations.first()
        return t.description if t else None

    def __str__(self):
        return self.title or str(self.pk)
