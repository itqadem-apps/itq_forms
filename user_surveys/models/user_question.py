from django.db import models

from .user_section import UserSection
from .user_survey import UserSurvey


class UserQuestion(models.Model):
    # Question type constants (self-contained, no dependency on surveys.models)
    TYPE_TEXT = "text"
    TYPE_TEXTAREA = "textarea"
    TYPE_NUMBER = "number"
    TYPE_FILE = "file"
    TYPE_DATE = "date"
    TYPE_TIME = "time"
    TYPE_DATETIME = "datetime"
    TYPE_RADIO = "radio"
    TYPE_CHECKBOX = "checkbox"
    TYPE_DROPDOWN = "dropdown"
    TYPE_RADIO_GRID = "radio_grid"
    TYPE_CHECKBOX_GRID = "checkbox_grid"

    SINGLE_SELECT_TYPES = (TYPE_RADIO, TYPE_DROPDOWN)
    MULTI_SELECT_TYPES = (TYPE_CHECKBOX,)
    GRID_TYPES = (TYPE_RADIO_GRID, TYPE_CHECKBOX_GRID)
    MCQ_TYPES = SINGLE_SELECT_TYPES + MULTI_SELECT_TYPES
    FREE_INPUT_TYPES = (TYPE_TEXT, TYPE_TEXTAREA, TYPE_DATE, TYPE_TIME, TYPE_DATETIME, TYPE_NUMBER, TYPE_FILE)

    class Meta:
        ordering = ["section__order", "order"]

    origin_id = models.IntegerField(null=True, blank=True, db_index=True)
    user_survey = models.ForeignKey(UserSurvey, on_delete=models.CASCADE, related_name="questions")
    section = models.ForeignKey(UserSection, on_delete=models.CASCADE, related_name="questions", null=True, blank=True)
    answer_time = models.DurationField(null=True, blank=True)
    order = models.IntegerField(default=1, null=True, blank=True)
    is_required = models.BooleanField(default=False)
    type = models.CharField(max_length=100, null=True, blank=True)
    cover_asset_id = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    translations = models.JSONField(default=dict, blank=True)
