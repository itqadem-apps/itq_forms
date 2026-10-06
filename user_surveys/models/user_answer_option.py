from django.db import models

from .user_answer_schema import UserAnswerSchema
from .user_classification import UserClassification
from .user_question import UserQuestion
from .user_section import UserSection
from .user_survey import UserSurvey


class UserAnswerOption(models.Model):
    class Meta:
        ordering = ["order"]

    # int4 against an int8 source pk. Deliberate, not an oversight: the
    # ruling and its measurements are on `UserMaterial.origin_id` and in
    # `tools/audit_snapshot_origin_id_headroom.sql`, and bind all eight.
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
    # The enrolment copy of the author's edge (`forms:AD-3`), targeting the learner's own question.
    flow_action = models.CharField(
        max_length=16,
        choices=[("fall_through", "Fall through"), ("go_to", "Go to"), ("terminate", "Terminate")],
        default="fall_through",
        db_default="fall_through",  # the previous image's enrolment copy inserts without it
    )
    flow_target = models.ForeignKey(
        UserQuestion, on_delete=models.SET_NULL, null=True, blank=True, related_name="incoming_edges"
    )
    translations = models.JSONField(default=dict, blank=True)
