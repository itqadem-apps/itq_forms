from django.contrib.auth import get_user_model
from django.db import models

from .survey import Survey

UserModel = get_user_model()


class Usage(models.Model):
    user = models.ForeignKey(UserModel, on_delete=models.SET_NULL, null=True, blank=True)
    survey = models.ForeignKey(Survey, on_delete=models.SET_NULL, null=True, blank=True)
    order_id = models.UUIDField()
    usage_limit = models.PositiveBigIntegerField(default=0)
    used_count = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    collection = models.ForeignKey(
        "survey_collections.SurveyCollection",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
