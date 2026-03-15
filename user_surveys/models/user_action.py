from django.db import models

from .user_survey import UserSurvey


class UserAction(models.Model):
    class Meta:
        ordering = ["id"]

    origin_id = models.IntegerField(null=True, blank=True, db_index=True)
    user_survey = models.ForeignKey(UserSurvey, on_delete=models.CASCADE, related_name="actions")
    upper_limit = models.FloatField(default=0)
    lower_limit = models.FloatField(default=0)
    translations = models.JSONField(default=dict, blank=True)
