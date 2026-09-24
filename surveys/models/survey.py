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

    #: What :attr:`primary_locale` answers for a survey whose primary language
    #: has never been set — the value `_build_translations` has always used for
    #: a survey with no translations at all.
    PRIMARY_LANGUAGE_FALLBACK = "default"

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
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Deleted At"))

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
    organization_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("Organization ID"),
    )
    cover_id = models.CharField(max_length=255, null=True, blank=True)
    thumb_id = models.CharField(max_length=255, null=True, blank=True)

    primary_language = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        verbose_name=_("Primary Language"),
        help_text=_(
            "The language this survey's body text is authored in. Read it through "
            "Survey.primary_locale, never directly. It decides which language key "
            "the legacy title/description/text columns fall back into when a "
            "learner enrols, so changing it on a survey that already has content "
            "mislabels that content until every row is re-saved."
        ),
    )

    @property
    def primary_locale(self) -> str:
        """The survey's primary locale: the language its body text is authored
        in. `forms:AD-1`.

        Every consumer of "the primary language" goes through here rather than
        writing its own query. There were three separate expressions of the
        idea before — this property, :attr:`language`, and the enrolment
        snapshot — each a chance for the service to hold two answers at once,
        which is the whole failure this pins shut. The surveys admin builder
        reads this value over GraphQL as ``Survey.primaryLanguage``; it must
        not derive one of its own, because a second derivation is a second
        definition however carefully it is written.

        This reads a stored column rather than deriving a value from the
        translations that happen to exist. A derived primary moves the moment
        an author adds a translation, and `create_survey_snapshot` freezes the
        primary into each learner's own records at enrolment — so a move would
        permanently mislabel every learner who enrolled between the move and a
        re-save of the body text, with no later edit able to reach them. The
        column does not move unless someone moves it.

        Falls back to :attr:`PRIMARY_LANGUAGE_FALLBACK` where the column is
        unset, which is what the snapshot has always done for a survey with no
        translations.
        """
        return self.primary_language or self.PRIMARY_LANGUAGE_FALLBACK

    @property
    def title(self):
        """The title in the survey's primary locale — see :attr:`primary_locale`.

        ``None`` where the survey has no translation in that locale, including
        the case where it has no translations at all.
        """
        t = self.translations.filter(language=self.primary_locale).first()
        return t.title if t else None

    @property
    def language(self):
        """The survey's primary locale, or ``None`` where it has never been set.

        Differs from :attr:`primary_locale` only in that case: this one reports
        the absence rather than substituting ``PRIMARY_LANGUAGE_FALLBACK``.
        """
        return self.primary_language or None

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