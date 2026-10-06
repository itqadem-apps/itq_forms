from django.db import models
from django.utils.translation import gettext_lazy as _

from .answer_schema import AnswerSchema
from classifications.models import Classification
from .question import Question
from .section import Section
from .survey import Survey


class FlowAction(models.TextChoices):
    """Where an answer sends the learner (`forms:AD-3`). Fall-through is stored explicitly, never
    as null."""

    FALL_THROUGH = "fall_through", _("Fall through")
    GO_TO = "go_to", _("Go to")
    TERMINATE = "terminate", _("Terminate")


class AnswerSchemaOption(models.Model):
    class Meta:
        ordering = ["order"]

    survey = models.ForeignKey(Survey, on_delete=models.CASCADE)
    # Nullable for a sectionless question (`forms:AD-9`), and SET_NULL so removing a section can
    # never cascade away the schema of a question that no longer sits in it.
    section = models.ForeignKey(Section, on_delete=models.SET_NULL, null=True, blank=True)
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
    # The option's edge (`forms:AD-3`): `flow_target` is set if and only if `flow_action` is go_to,
    # and must sit after this option's question (`forms:AD-5`); `surveys.flow` checks both.
    # `db_default` too, so a pod still running the previous image can insert an option while
    # this column is being added.
    flow_action = models.CharField(
        max_length=16, choices=FlowAction.choices, default=FlowAction.FALL_THROUGH, db_default=FlowAction.FALL_THROUGH
    )
    flow_target = models.ForeignKey(
        Question, on_delete=models.SET_NULL, null=True, blank=True, related_name="incoming_edges"
    )

    def save(self, *args, **kwargs):
        if not self.pk:
            self.order = self.schema.options.count() + 1
        super().save(*args, **kwargs)
