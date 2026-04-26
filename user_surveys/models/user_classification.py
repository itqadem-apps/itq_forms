from django.db import models

from .user_survey import UserSurvey


class UserClassification(models.Model):
    class Meta:
        ordering = ["created_at"]

    origin_id = models.IntegerField(null=True, blank=True, db_index=True)
    user_survey = models.ForeignKey(UserSurvey, on_delete=models.CASCADE, related_name="survey_classifications")
    score = models.IntegerField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    translations = models.JSONField(default=dict, blank=True)
