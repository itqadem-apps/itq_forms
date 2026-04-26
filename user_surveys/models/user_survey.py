from django.contrib.auth import get_user_model
from django.db import models
from django.utils.translation import gettext_lazy as _

from surveys.models import Survey
from survey_collections.models import SurveyCollection

from accounts.models import Child

UserModel = get_user_model()


class UserSurvey(models.Model):
    # Evaluation type constants (self-contained, no dependency on surveys.models)
    EVALUATION_TYPE_AUTOMATIC = "automatic_evaluation"
    EVALUATION_TYPE_MANUAL = "manual_evaluation"

    # Termination reason constants
    TERMINATION_COMPLETED = "completed"
    TERMINATION_TIME_EXPIRED = "time_expired"
    TERMINATION_ENDING_OPTION = "ending_option"
    TERMINATION_CHOICES = (
        (TERMINATION_COMPLETED, "Completed by user"),
        (TERMINATION_TIME_EXPIRED, "Time expired"),
        (TERMINATION_ENDING_OPTION, "Ending option threshold reached"),
    )

    class Meta:
        ordering = ["submitted_at"]

    # ── reference to source ──────────────────────────────────────────
    survey = models.ForeignKey(Survey, on_delete=models.SET_NULL, null=True, blank=True)

    # ── user / enrollment ────────────────────────────────────────────
    collection = models.ForeignKey(SurveyCollection, on_delete=models.SET_NULL, null=True, blank=True)
    user = models.ForeignKey(UserModel, on_delete=models.SET_NULL, null=True, blank=True)
    child = models.ForeignKey(Child, on_delete=models.SET_NULL, null=True, blank=True)

    # ── snapshot: Survey fields ──────────────────────────────────────
    status = models.CharField(max_length=20, null=True, blank=True)
    survey_type = models.CharField(max_length=255, null=True, blank=True)
    display_option = models.CharField(max_length=255, null=True, blank=True)
    is_timed = models.BooleanField(default=False)
    time_limit = models.DurationField(null=True, blank=True)
    is_for_child = models.BooleanField(default=False)

    # evaluation config
    is_evaluable = models.BooleanField(default=False)
    evaluation_type = models.CharField(max_length=255, null=True, blank=True)
    use_score = models.BooleanField(default=True)
    use_classifications = models.BooleanField(default=False)
    use_recommendations = models.BooleanField(default=False)
    use_actions = models.BooleanField(default=False)
    allow_end_based_on_answer_repeat = models.BooleanField(default=False)
    answers_count_to_end = models.IntegerField(default=0)
    end_based_on_answer_repeat_in_row = models.BooleanField(default=False)

    # anti-cheating config (snapshotted from Survey)
    enable_anti_cheat = models.BooleanField(default=False)
    lock_answers = models.BooleanField(default=False)
    randomize_questions = models.BooleanField(default=False)
    randomize_options = models.BooleanField(default=False)

    # denormalised assets
    cover_id = models.CharField(max_length=255, null=True, blank=True)
    thumb_id = models.CharField(max_length=255, null=True, blank=True)

    # denormalised category (plain UUID, not FK)
    category_id_snapshot = models.UUIDField(null=True, blank=True)
    sponsor = models.PositiveIntegerField(null=True, blank=True)
    survey_created_at = models.DateTimeField(null=True, blank=True)
    survey_updated_at = models.DateTimeField(null=True, blank=True)

    translations = models.JSONField(default=dict, blank=True)

    # ── assessment state ─────────────────────────────────────────────
    session_token = models.UUIDField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    tab_switch_count = models.IntegerField(default=0)
    count_of_ending_options = models.IntegerField(default=0)
    termination_reason = models.CharField(
        max_length=20, choices=TERMINATION_CHOICES, null=True, blank=True,
    )
    evaluated_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    score = models.IntegerField(null=True, blank=True)
    last_question = models.ForeignKey(
        "user_surveys.UserQuestion", on_delete=models.SET_NULL, null=True, blank=True
    )
    classifications = models.ManyToManyField(
        "user_surveys.UserClassification", through="UserSurveyClassification"
    )
    recommendations = models.ManyToManyField(
        "user_surveys.UserRecommendation", through="UserSurveyRecommendation"
    )
    action = models.ForeignKey(
        "user_surveys.UserAction", on_delete=models.SET_NULL, null=True, blank=True
    )