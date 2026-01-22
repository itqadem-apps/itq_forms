from django.db import models
from django.utils.translation import gettext_lazy as _

from .survey import Survey


class Action(models.Model):
    class Meta:
        ordering = ["id"]

    title = models.CharField(max_length=255, null=True, blank=True, default=None, verbose_name=_("Title"))
    description = models.TextField(null=True, blank=True, default=None, verbose_name=_("Description"))
    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name="actions")
    upper_limit = models.FloatField(default=0, verbose_name=_("Upper Limit"))
    lower_limit = models.FloatField(default=0, verbose_name=_("Lower Limit"))
