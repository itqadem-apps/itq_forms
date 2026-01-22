from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _

from taxonomy.models import Category

from .status import Status

UserModel = get_user_model()


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
    ASSESSMENT_TYPE_QUESTIONNAIRE = "questionnaire"
    ASSESSMENT_TYPE_CURRICULUM = "curriculum"
    ASSESSMENT_TYPE_EXAM = "exam"
    ASSESSMENT_TYPE_SMART_FORM = "smart_form"
    ASSESSMENT_TYPES = (
        (ASSESSMENT_TYPE_SURVEY, _("Survey")),
        (ASSESSMENT_TYPE_QUESTIONNAIRE, _("Questionnaire")),
        (ASSESSMENT_TYPE_CURRICULUM, _("Curriculum")),
        (ASSESSMENT_TYPE_EXAM, _("Exam")),
        (ASSESSMENT_TYPE_SMART_FORM, _("Smart Form")),
    )

    EVALUATION_TYPE_AUTOMATIC_EVALUATION = "automatic_evaluation"
    EVALUATION_TYPE_MANUAL_EVALUATION = "manual_evaluation"
    EVALUATION_TYPES = (
        (EVALUATION_TYPE_AUTOMATIC_EVALUATION, _("Automatic Evaluation")),
        (EVALUATION_TYPE_MANUAL_EVALUATION, _("Manual Evaluation")),
    )

    SEARCH_INDEX = ("title", "description", "short_description")

    class Meta:
        ordering = ["-created_at"]

    title = models.CharField(max_length=255, null=True, blank=True, verbose_name=_("Title"))
    description = models.TextField(null=True, blank=True, verbose_name=_("Description"))
    short_description = models.CharField(
        max_length=300, null=True, blank=True, verbose_name=_("Short Description")
    )
    slug = models.SlugField(max_length=255, null=True, blank=True)
    language = models.CharField(
        max_length=64,
        choices=settings.LANGUAGES,
        default=settings.LANGUAGE_CODE,
        null=True,
        blank=True,
        verbose_name=_("Language"),
    )
    status = models.ForeignKey(
        Status,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="current_surveys",
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
    price = models.FloatField(default=0)

    def __str__(self):
        return str(self.title)

    def update_status(self, status: str, user: UserModel | None = None) -> Status:
        entry = Status.objects.create(survey=self, user=user, status=status)
        self.status = entry
        self.save(update_fields=["status"])
        return entry

    @property
    def get_language(self):
        return dict(settings.LANGUAGES).get(self.language)

    @property
    def get_status(self):
        if self.status_id is None:
            return None
        return self.status.get_status

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
