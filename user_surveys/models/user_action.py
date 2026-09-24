from django.db import models

from .user_survey import UserSurvey


class UserAction(models.Model):
    class Meta:
        ordering = ["id"]

    # int4 against an int8 source pk. Deliberate, not an oversight: the
    # ruling and its measurements are on `UserMaterial.origin_id` and in
    # `tools/audit_snapshot_origin_id_headroom.sql`, and bind all eight.
    origin_id = models.IntegerField(null=True, blank=True, db_index=True)
    user_survey = models.ForeignKey(UserSurvey, on_delete=models.CASCADE, related_name="actions")
    upper_limit = models.FloatField(default=0)
    lower_limit = models.FloatField(default=0)
    translations = models.JSONField(default=dict, blank=True)
