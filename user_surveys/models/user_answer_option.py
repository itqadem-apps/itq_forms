from django.db import models

from .user_answer_schema import UserAnswerSchema
from .user_classification import UserClassification
from .user_question import UserQuestion
from .user_section import UserSection
from .user_survey import UserSurvey


class UserAnswerOption(models.Model):
    class Meta:
        ordering = ["order"]

    origin_id = models.IntegerField(null=True, blank=True, db_index=True)
    user_survey = models.ForeignKey(UserSurvey, on_delete=models.CASCADE, related_name="answer_options")
    section = models.ForeignKey(UserSection, on_delete=models.CASCADE, null=True, blank=True)
    question = models.ForeignKey(UserQuestion, on_delete=models.CASCADE, null=True, blank=True)
    schema = models.ForeignKey(UserAnswerSchema, on_delete=models.CASCADE, related_name="options")
    classification = models.ForeignKey(UserClassification, on_delete=models.SET_NULL, null=True, blank=True)
    score = models.IntegerField(default=None, null=True, blank=True)
    image_asset_id = models.CharField(max_length=255, null=True, blank=True)
    is_row = models.BooleanField(default=None, null=True, blank=True)
    is_column = models.BooleanField(default=None, null=True, blank=True)
    ending_option = models.BooleanField(default=None, null=True, blank=True)
    order = models.IntegerField(default=1)
    translations = models.JSONField(default=dict, blank=True)
