from django.db import models
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _

from .section import Section
from .survey import Survey


class Question(models.Model):
    QUESTION_TYPE_TEXT = "text"
    QUESTION_TYPE_TEXTAREA = "textarea"
    QUESTION_TYPE_NUMBER = "number"
    QUESTION_TYPE_FILE = "file"
    QUESTION_TYPE_DATE = "date"
    QUESTION_TYPE_TIME = "time"
    QUESTION_TYPE_DATETIME = "datetime"
    QUESTION_TYPE_RADIO_MCQ = "radio"
    QUESTION_TYPE_CHECKBOX_MCQ = "checkbox"
    QUESTION_TYPE_DROPDOWN_MCQ = "dropdown"
    QUESTION_TYPE_RADIO_GRID = "radio_grid"
    QUESTION_TYPE_CHECKBOX_GRID = "checkbox_grid"
    QUESTION_TYPE_CHOICES = (
        (QUESTION_TYPE_TEXT, _("Short Answer")),
        (QUESTION_TYPE_TEXTAREA, _("Paragraph")),
        (QUESTION_TYPE_NUMBER, _("Number")),
        (QUESTION_TYPE_FILE, _("File Upload")),
        (QUESTION_TYPE_DATE, _("Date")),
        (QUESTION_TYPE_TIME, _("Time")),
        (QUESTION_TYPE_DATETIME, _("Date and Time")),
        (QUESTION_TYPE_RADIO_MCQ, _("Radio MCQ Answer")),
        (QUESTION_TYPE_CHECKBOX_MCQ, _("Checkbox MCQ Answer")),
        (QUESTION_TYPE_DROPDOWN_MCQ, _("Dropdown MCQ Answer")),
        (QUESTION_TYPE_RADIO_GRID, _("Radio Grid Answer")),
        (QUESTION_TYPE_CHECKBOX_GRID, _("Checkbox Grid Answer")),
    )

    class Meta:
        ordering = ["section__order", "order"]

    title = models.CharField(max_length=255, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    answer_time = models.DurationField(verbose_name=_("Answer Time"), null=True, blank=True)
    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name="questions", null=True, blank=True)
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name="questions", null=True, blank=True)
    order = models.IntegerField(default=1, null=True, blank=True)
    is_required = models.BooleanField(default=False)
    type = models.CharField(
        max_length=100,
        choices=QUESTION_TYPE_CHOICES,
        default=QUESTION_TYPE_RADIO_MCQ,
        null=True,
        blank=True,
    )
    cover_asset_id = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_created=True, default=now, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    @property
    def mcq_types(self):
        return [self.QUESTION_TYPE_RADIO_MCQ, self.QUESTION_TYPE_CHECKBOX_MCQ, self.QUESTION_TYPE_DROPDOWN_MCQ]

    @property
    def grid_types(self):
        return [self.QUESTION_TYPE_RADIO_GRID, self.QUESTION_TYPE_CHECKBOX_GRID]

    def update_answer_schema(self):
        if not hasattr(self, "answer_schema"):
            return

        from .answer_schema import AnswerSchema

        if self.type not in self.mcq_types and self.type not in self.grid_types:
            self.answer_schema.type = self.type
            self.answer_schema.with_file = False
            self.answer_schema.is_mcq = False
            self.answer_schema.is_grid = False
            self.answer_schema.save()
            self.answer_schema.options.all().delete()
            return

        if self.type in self.mcq_types:
            if not self.answer_schema.is_mcq:
                self.answer_schema.options.all().delete()
            self.answer_schema.type = self.type
            self.answer_schema.with_file = self.type != self.QUESTION_TYPE_DROPDOWN_MCQ
            self.answer_schema.is_mcq = True
            self.answer_schema.is_grid = False
            self.answer_schema.save()
            if self.answer_schema.options.count() == 0:
                self.answer_schema.options.create(
                    survey_id=self.survey_id,
                    section_id=self.section_id,
                    question_id=self.id,
                    schema_id=self.answer_schema_id,
                )
            return

        if self.type in self.grid_types:
            if not self.answer_schema.is_grid:
                self.answer_schema.options.all().delete()
            self.answer_schema.type = self.type
            self.answer_schema.with_file = False
            self.answer_schema.is_mcq = False
            self.answer_schema.is_grid = True
            self.answer_schema.save()
            if self.answer_schema.options.count() == 0:
                self.answer_schema.options.create(
                    survey_id=self.survey_id,
                    section_id=self.section_id,
                    question_id=self.id,
                    schema_id=self.answer_schema_id,
                    is_row=True,
                    is_column=False,
                )
                self.answer_schema.options.create(
                    survey_id=self.survey_id,
                    section_id=self.section_id,
                    question_id=self.id,
                    schema_id=self.answer_schema_id,
                    is_row=False,
                    is_column=True,
                )

    def save(self, *args, **kwargs):
        if not self.pk and self.section_id:
            self.order = self.section.questions.count() + 1
        super().save(*args, **kwargs)
