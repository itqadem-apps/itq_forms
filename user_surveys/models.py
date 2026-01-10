from django.contrib.auth import get_user_model
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

from surveys.models import (
    Action,
    AnswerSchemaOption,
    Classification,
    Question,
    Recommendation,
    Survey,
)

UserModel = get_user_model()


class UserAssessment(models.Model):
    class Meta:
        ordering = ["submitted_at"]

    is_paid = models.BooleanField(default=False)
    survey = models.ForeignKey(Survey, on_delete=models.SET_NULL, null=True, blank=True)
    user = models.ForeignKey(UserModel, on_delete=models.SET_NULL, null=True, blank=True)
    child_id = models.CharField(max_length=255, null=True, blank=True)
    count_of_ending_options = models.IntegerField(default=0)
    evaluated_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    score = models.IntegerField(null=True, blank=True)
    progress = models.IntegerField(null=True, blank=True, default=0)
    last_question = models.ForeignKey(Question, on_delete=models.CASCADE, null=True, blank=True)
    classifications = models.ManyToManyField(Classification, through="UserAssessmentClassification")
    recommendations = models.ManyToManyField(Recommendation, through="UserAssessmentRecommendation")
    action = models.ForeignKey(Action, on_delete=models.SET_NULL, null=True, blank=True)


class UserAssessmentClassification(models.Model):
    user_assessment = models.ForeignKey(UserAssessment, on_delete=models.CASCADE)
    classification = models.ForeignKey(Classification, on_delete=models.CASCADE)
    count = models.IntegerField(default=0)


class UserAssessmentRecommendation(models.Model):
    user_assessment = models.ForeignKey(UserAssessment, on_delete=models.CASCADE)
    recommendation = models.ForeignKey(Recommendation, on_delete=models.CASCADE)
    count = models.IntegerField(default=0)


class UserAnswer(models.Model):
    class Meta:
        ordering = ["question__section__order", "question__order"]

    survey = models.ForeignKey(Survey, on_delete=models.SET_NULL, null=True, blank=True)
    user = models.ForeignKey(UserModel, on_delete=models.SET_NULL, null=True, blank=True)
    question = models.ForeignKey(Question, on_delete=models.SET_NULL, null=True, blank=True)
    question_title = models.CharField(max_length=255, null=True)
    user_assessment = models.ForeignKey(UserAssessment, on_delete=models.CASCADE, null=True, blank=True)
    answer = models.TextField(default=None, blank=True, null=True)
    type = models.CharField(
        max_length=50,
        choices=Question.QUESTION_TYPE_CHOICES,
        default=Question.QUESTION_TYPE_RADIO_MCQ,
    )
    selected_options = models.ManyToManyField(AnswerSchemaOption, blank=True)
    score = models.IntegerField(null=True, blank=True)
    order = models.IntegerField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if self.question_id:
            self.question_title = self.question.title
        super().save(*args, **kwargs)


@receiver(post_save, sender=UserAssessment)
def _create_user_assessment_tree(sender, instance: UserAssessment, created: bool, **kwargs):
    if not created or not instance.survey_id:
        return

    survey = instance.survey
    for idx, question in enumerate(survey.questions.all().order_by("section__order", "order"), start=1):
        UserAnswer.objects.create(
            user=instance.user,
            question=question,
            question_title=question.title,
            survey=instance.survey,
            user_assessment=instance,
            type=question.type,
            order=idx,
        )
