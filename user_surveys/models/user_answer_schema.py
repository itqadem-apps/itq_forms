from django.db import models

from .user_question import UserQuestion
from .user_section import UserSection
from .user_survey import UserSurvey


class UserAnswerSchema(models.Model):
    origin_id = models.IntegerField(null=True, blank=True, db_index=True)
    user_survey = models.ForeignKey(UserSurvey, on_delete=models.CASCADE, related_name="answer_schemas")
    section = models.ForeignKey(UserSection, on_delete=models.CASCADE, null=True, blank=True)
    question = models.OneToOneField(UserQuestion, on_delete=models.CASCADE, related_name="answer_schema")
    type = models.CharField(max_length=100, null=True, blank=True)
    with_file = models.BooleanField(default=False)
    is_mcq = models.BooleanField(default=False)
    is_grid = models.BooleanField(default=False)
