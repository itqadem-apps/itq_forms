from django.db import models
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _

from taxonomy.models import Category


class Survey(models.Model):
    DISPLAY_OPTION_BY_QUESTION = "by_question"
    DISPLAY_OPTION_BY_SECTION = "by_section"
    DISPLAY_OPTION_FULL_FORM = "full_form"
    DISPLAY_OPTIONS = (
        (DISPLAY_OPTION_BY_QUESTION, _("By Question")),
        (DISPLAY_OPTION_BY_SECTION, _("By Section")),
        (DISPLAY_OPTION_FULL_FORM, _("Full Form")),
    )

    ASSESSMENT_TYPE_SURVEY = "survey"
    ASSESSMENT_TYPE_ASSESSMENT = "assessment"
    ASSESSMENT_TYPE_CURRICULUM = "curriculum"
    ASSESSMENT_TYPE_EXAM = "exam"
    ASSESSMENT_TYPE_FORM = "form"
    ASSESSMENT_TYPES = (
        (ASSESSMENT_TYPE_SURVEY, _("Survey")),
        (ASSESSMENT_TYPE_ASSESSMENT, _("Assessment")),
        (ASSESSMENT_TYPE_CURRICULUM, _("Curriculum")),
        (ASSESSMENT_TYPE_EXAM, _("Exam")),
        (ASSESSMENT_TYPE_FORM, _("Form")),
    )

    EVALUATION_TYPE_AUTOMATIC_EVALUATION = "automatic_evaluation"
    EVALUATION_TYPE_MANUAL_EVALUATION = "manual_evaluation"
    EVALUATION_TYPES = (
        (EVALUATION_TYPE_AUTOMATIC_EVALUATION, _("Automatic Evaluation")),
        (EVALUATION_TYPE_MANUAL_EVALUATION, _("Manual Evaluation")),
    )

    STATUS_DRAFT = "draft"
    STATUS_PENDING = "pending"
    STATUS_PUBLISHED = "published"
    STATUS_ARCHIVED = "archived"
    STATUS_SUSPENDED = "suspended"
    STATUS_CANCELED = "canceled"
    STATUS_REJECTED = "rejected"
    STATUS_APPROVED = "approved"
    STATUS_STARTED = "started"
    STATUS_ENDED = "ended"
    STATUS_CHOICES = (
        (STATUS_DRAFT, _("Draft")),
        (STATUS_PENDING, _("Pending")),
        (STATUS_PUBLISHED, _("Published")),
        (STATUS_ARCHIVED, _("Archived")),
        (STATUS_SUSPENDED, _("Suspended")),
        (STATUS_CANCELED, _("Canceled")),
        (STATUS_REJECTED, _("Rejected")),
        (STATUS_APPROVED, _("Approved")),
        (STATUS_STARTED, _("Started")),
        (STATUS_ENDED, _("Ended")),
    )

    class Meta:
        ordering = ["-created_at"]

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
        verbose_name=_("Status"),
    )
    survey_type = models.CharField(
        max_length=255,
        choices=ASSESSMENT_TYPES,
        default=ASSESSMENT_TYPE_SURVEY,
        verbose_name=_("Survey Type"),
    )
    display_option = models.CharField(
        max_length=255,
        choices=DISPLAY_OPTIONS,
        default=DISPLAY_OPTION_BY_QUESTION,
        verbose_name=_("Display Option"),
    )
    is_timed = models.BooleanField(default=False, verbose_name=_("Is Timed"))
    time_limit = models.DurationField(null=True, blank=True, verbose_name=_("Time Limit"))
    is_for_child = models.BooleanField(default=False, verbose_name=_("Is For "))

    # evaluation settings
    is_evaluable = models.BooleanField(default=False, verbose_name=_("Is Evaluable"))
    evaluation_type = models.CharField(
        max_length=255,
        choices=EVALUATION_TYPES,
        default=EVALUATION_TYPE_AUTOMATIC_EVALUATION,
        null=True,
        blank=True,
        verbose_name=_("Evaluation Type"),
    )
    use_score = models.BooleanField(default=True, verbose_name=_("Use Score"))
    use_classifications = models.BooleanField(default=False, verbose_name=_("Use Classifications"))
    use_recommendations = models.BooleanField(default=False, verbose_name=_("Use Recommendations"))
    use_actions = models.BooleanField(default=False, verbose_name=_("Use Actions"))
    allow_end_based_on_answer_repeat = models.BooleanField(
        default=False, verbose_name=_("Allow Ending Based on Repeating Answer")
    )
    answers_count_to_end = models.IntegerField(default=0, verbose_name=_("Answers Count to End"))
    end_based_on_answer_repeat_in_row = models.BooleanField(
        default=False, verbose_name=_("End Based on Repeating Answer in Row")
    )
    # anti-cheating config
    enable_anti_cheat = models.BooleanField(default=False, verbose_name=_("Enable Anti-Cheat"))
    lock_answers = models.BooleanField(default=False, verbose_name=_("Lock Answers"))
    randomize_questions = models.BooleanField(default=False, verbose_name=_("Randomize Questions"))
    randomize_options = models.BooleanField(default=False, verbose_name=_("Randomize Options"))

    allow_update_answer_options_scores_based_on_classification = models.BooleanField(
        default=False,
        verbose_name=_("Allow Update Answer Options Scores Based on Classification"),
    )
    allow_update_answer_options_text_based_on_classification = models.BooleanField(
        default=False,
        verbose_name=_("Allow Update Answer Options Text Based on Classification"),
    )
    create_option_for_each_classification = models.BooleanField(
        default=False, verbose_name=_("Create Option for Each Classification")
    )

    created_at = models.DateTimeField(auto_created=True, default=now, blank=True, verbose_name=_("Created At"))
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True, verbose_name=_("Updated At"))

    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assessments",
    )
    sponsor = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Sponsor"),
    )
    cover_id = models.CharField(max_length=255, null=True, blank=True)
    thumb_id = models.CharField(max_length=255, null=True, blank=True)

    @property
    def title(self):
        """Convenience accessor: returns the title from the first translation."""
        t = self.translations.first()
        return t.title if t else None

    @property
    def language(self):
        """Convenience accessor: returns the language from the first translation."""
        t = self.translations.first()
        return t.language if t else None

    def __str__(self):
        return str(self.title or self.pk)

    @property
    def get_status(self):
        return dict(self.STATUS_CHOICES).get(self.status)

    @property
    def get_evaluation_type(self):
        return dict(self.EVALUATION_TYPES).get(self.evaluation_type)

    @property
    def get_survey_type(self):
        return dict(self.ASSESSMENT_TYPES).get(self.survey_type)

    @property
    def get_model_name(self):
        return self.get_survey_type

    @property
    def get_display_option(self):
        return dict(self.DISPLAY_OPTIONS).get(self.display_option)