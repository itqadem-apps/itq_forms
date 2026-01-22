from django.db import models
from django.utils.translation import gettext_lazy as _

from .answer_schema import AnswerSchema
from .classification import Classification
from .question import Question
from .section import Section
from .survey import Survey


class AnswerSchemaOption(models.Model):
    class Meta:
        ordering = ["order"]

    survey = models.ForeignKey(Survey, on_delete=models.CASCADE)
    section = models.ForeignKey(Section, on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    schema = models.ForeignKey(AnswerSchema, on_delete=models.CASCADE, related_name="options")
    text = models.TextField(null=True, blank=True)
    score = models.IntegerField(default=None, null=True, blank=True)
    classification = models.ForeignKey(Classification, on_delete=models.CASCADE, null=True, blank=True)
    image_asset_id = models.CharField(max_length=255, null=True, blank=True)
    is_row = models.BooleanField(default=None, null=True, blank=True)
    is_column = models.BooleanField(default=None, null=True, blank=True)
    ending_option = models.BooleanField(default=None, null=True, blank=True, verbose_name=_("Ending Option"))
    order = models.IntegerField(default=1)

    def save(self, *args, **kwargs):
        if not self.pk:
            self.order = self.schema.options.count() + 1
        super().save(*args, **kwargs)
