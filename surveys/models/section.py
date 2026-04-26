from django.db import models
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _

from .survey import Survey


class Section(models.Model):
    class Meta:
        ordering = ["order"]

    SUBMIT_ACTION_NEXT = "next"
    SUBMIT_ACTION_JUMP = "jump"
    SUBMIT_ACTIONS = (
        (SUBMIT_ACTION_NEXT, _("Next section")),
        (SUBMIT_ACTION_JUMP, _("Jump to target section")),
    )

    title = models.CharField(max_length=255, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name="sections")
    order = models.IntegerField(default=1, null=True, blank=True)
    is_hidden = models.BooleanField(default=False)
    cover_asset_id = models.CharField(max_length=255, null=True, blank=True)
    submit_action = models.CharField(max_length=90, choices=SUBMIT_ACTIONS, default=SUBMIT_ACTION_NEXT)
    submit_action_target = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True)
    created_at = models.DateTimeField(auto_created=True, default=now, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.pk:
            self.order = self.survey.sections.count() + 1
        super().save(*args, **kwargs)
