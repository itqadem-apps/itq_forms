from django.db import models

from .user_classification import UserClassification
from .user_recommendation import UserRecommendation
from .user_survey import UserSurvey


class UserSurveyClassification(models.Model):
    user_survey = models.ForeignKey(UserSurvey, on_delete=models.CASCADE)
    classification = models.ForeignKey(UserClassification, on_delete=models.CASCADE)
    count = models.IntegerField(default=0)


class UserSurveyRecommendation(models.Model):
    user_survey = models.ForeignKey(UserSurvey, on_delete=models.CASCADE)
    recommendation = models.ForeignKey(UserRecommendation, on_delete=models.CASCADE)
    count = models.IntegerField(default=0)
