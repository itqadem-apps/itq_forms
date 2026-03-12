from django.contrib.auth import get_user_model
from django.db import models

from .user_answer_option import UserAnswerOption
from .user_question import UserQuestion
from .user_survey import UserSurvey

UserModel = get_user_model()


class UserAnswer(models.Model):
    class Meta:
        ordering = ["question__section__order", "question__order"]
        constraints = [
            models.UniqueConstraint(
                fields=["user_survey", "question"],
                name="uq_user_answer_survey_question",
            ),
        ]

    user = models.ForeignKey(UserModel, on_delete=models.SET_NULL, null=True, blank=True)
    question = models.ForeignKey(UserQuestion, on_delete=models.SET_NULL, null=True, blank=True)
    user_survey = models.ForeignKey(UserSurvey, on_delete=models.CASCADE, null=True, blank=True)
    answer = models.TextField(default=None, blank=True, null=True)
    type = models.CharField(max_length=50, null=True, blank=True)
    selected_options = models.ManyToManyField(UserAnswerOption, blank=True)
    score = models.IntegerField(null=True, blank=True)
    order = models.IntegerField(null=True, blank=True)
    answered_at = models.DateTimeField(null=True, blank=True)
    time_spent = models.DurationField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
