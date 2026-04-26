from django.db import models

from .user_survey import UserSurvey


class UserSection(models.Model):
    class Meta:
        ordering = ["order"]

    origin_id = models.IntegerField(null=True, blank=True, db_index=True)
    user_survey = models.ForeignKey(UserSurvey, on_delete=models.CASCADE, related_name="sections")
    order = models.IntegerField(default=1, null=True, blank=True)
    is_hidden = models.BooleanField(default=False)
    cover_asset_id = models.CharField(max_length=255, null=True, blank=True)
    submit_action = models.CharField(max_length=90, null=True, blank=True)
    submit_action_target = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    translations = models.JSONField(default=dict, blank=True)
