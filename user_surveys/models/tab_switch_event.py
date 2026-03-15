from django.db import models

from .user_survey import UserSurvey


class TabSwitchEvent(models.Model):
    class Meta:
        ordering = ["-created_at"]

    user_survey = models.ForeignKey(UserSurvey, on_delete=models.CASCADE, related_name="tab_switch_events")
    event_type = models.CharField(max_length=20)  # "blur", "visibility_hidden", etc.
    created_at = models.DateTimeField(auto_now_add=True)
