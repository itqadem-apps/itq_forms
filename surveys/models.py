from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _
from uuid import uuid4

from taxonomy.models import Category

UserModel = get_user_model()


class AssetType(models.TextChoices):
    COVER = "cover", _("Cover")
    THUMBNAIL = "thumbnail", _("Thumbnail")
    ATTACHMENT = "attachment", _("Attachment")


class Status(models.Model):
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

    STATUS_DRAFT_CHOICE = (STATUS_DRAFT, _("Draft"))
    STATUS_PENDING_CHOICE = (STATUS_PENDING, _("Pending"))
    STATUS_PUBLISHED_CHOICE = (STATUS_PUBLISHED, _("Published"))
    STATUS_ARCHIVED_CHOICE = (STATUS_ARCHIVED, _("Archived"))
    STATUS_SUSPENDED_CHOICE = (STATUS_SUSPENDED, _("Suspended"))
    STATUS_CANCELED_CHOICE = (STATUS_CANCELED, _("Canceled"))
    STATUS_REJECTED_CHOICE = (STATUS_REJECTED, _("Rejected"))
    STATUS_APPROVED_CHOICE = (STATUS_APPROVED, _("Approved"))
    STATUS_STARTED_CHOICE = (STATUS_STARTED, _("Started"))
    STATUS_ENDED_CHOICE = (STATUS_ENDED, _("Ended"))

    STATUS_CHOICES = (
        STATUS_DRAFT_CHOICE,
        STATUS_PENDING_CHOICE,
        STATUS_PUBLISHED_CHOICE,
        STATUS_ARCHIVED_CHOICE,
        STATUS_SUSPENDED_CHOICE,
        STATUS_CANCELED_CHOICE,
        STATUS_REJECTED_CHOICE,
        STATUS_APPROVED_CHOICE,
        STATUS_STARTED_CHOICE,
        STATUS_ENDED_CHOICE,
    )

    class Meta:
        verbose_name = _("Status")
        verbose_name_plural = _("Status")

    survey = models.ForeignKey("Survey", on_delete=models.CASCADE, related_name="status_log")
    user = models.ForeignKey(
        UserModel,
        on_delete=models.CASCADE,
        related_name="%(class)s_activity_log",
        null=True,
        blank=True,
    )
    at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)

    @property
    def get_status(self):
        return dict(self.STATUS_CHOICES).get(self.status)


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
    ASSESSMENT_TYPE_COLLECTION = "collection"
    ASSESSMENT_TYPES = (
        (ASSESSMENT_TYPE_SURVEY, _("Survey")),
        (ASSESSMENT_TYPE_QUESTIONNAIRE, _("Questionnaire")),
        (ASSESSMENT_TYPE_CURRICULUM, _("Curriculum")),
        (ASSESSMENT_TYPE_EXAM, _("Exam")),
        (ASSESSMENT_TYPE_SMART_FORM, _("Smart Form")),
        (ASSESSMENT_TYPE_COLLECTION, _("Collection")),
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

    # timestamps
    created_at = models.DateTimeField(auto_created=True, default=now, blank=True, verbose_name=_("Created At"))
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True, verbose_name=_("Updated At"))

    # relationships
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

class SurveyMediaAsset(models.Model):
    class Meta:
        indexes = [
            models.Index(fields=["survey"], name="ix_survey_media_assets_survey"),
        ]

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name="assets")
    asset_id = models.CharField(max_length=255)
    asset_type = models.CharField(max_length=32, choices=AssetType.choices)


class HasSoftDelete(models.Model):
    class Meta:
        abstract = True

    deleted_at = models.DateTimeField(blank=True, null=True)


class Action(models.Model):
    class Meta:
        ordering = ["id"]

    title = models.CharField(max_length=255, null=True, blank=True, default=None, verbose_name=_("Title"))
    description = models.TextField(null=True, blank=True, default=None, verbose_name=_("Description"))
    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name="actions")
    upper_limit = models.FloatField(default=0, verbose_name=_("Upper Limit"))
    lower_limit = models.FloatField(default=0, verbose_name=_("Lower Limit"))


class RecommendedMaterial(models.Model):
    action = models.ForeignKey(Action, on_delete=models.CASCADE, related_name="recommended_materials")
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey()


class Classification(HasSoftDelete):
    class Meta:
        ordering = ["created_at"]
        verbose_name = _("Classification")
        verbose_name_plural = _("Classifications")

    name = models.CharField(max_length=255, null=True, blank=True)
    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name="classifications", null=True, blank=True)
    score = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_created=True, default=now, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    def __str__(self):
        return self.name or ""


class Section(models.Model):
    class Meta:
        ordering = ["order"]

    SUBMIT_ACTION_NEXT = "next"
    SUBMIT_ACTION_JUMP = "jump"
    SUBMIT_ACTIONS = (
        (SUBMIT_ACTION_NEXT, _("Next section")),
        (SUBMIT_ACTION_JUMP, _("Jump to target section")),
    )

    title = models.CharField(max_length=255, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name="sections")
    order = models.IntegerField(default=1, null=True, blank=True)
    is_hidden = models.BooleanField(default=False)
    cover_asset_id = models.CharField(max_length=255, null=True, blank=True)
    submit_action = models.CharField(max_length=90, choices=SUBMIT_ACTIONS, default=SUBMIT_ACTION_NEXT)
    submit_action_target = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True)
    created_at = models.DateTimeField(auto_created=True, default=now, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.pk:
            self.order = self.survey.sections.count() + 1
        super().save(*args, **kwargs)


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


class AnswerSchema(models.Model):
    survey = models.ForeignKey(Survey, on_delete=models.CASCADE)
    section = models.ForeignKey(Section, on_delete=models.CASCADE)
    question = models.OneToOneField(Question, on_delete=models.CASCADE, related_name="answer_schema")
    type = models.CharField(max_length=100, choices=Question.QUESTION_TYPE_CHOICES, default=Question.QUESTION_TYPE_RADIO_MCQ)
    with_file = models.BooleanField(default=False)
    is_mcq = models.BooleanField(default=False)
    is_grid = models.BooleanField(default=False)


class AnswerSchemaOption(models.Model):
    class Meta:
        ordering = ["order"]

    survey = models.ForeignKey(Survey, on_delete=models.CASCADE)
    section = models.ForeignKey(Section, on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    schema = models.ForeignKey(AnswerSchema, on_delete=models.CASCADE, related_name="options")
    text = models.TextField(null=True, blank=True)
    score = models.IntegerField(default=None, null=True, blank=True)
    classification = models.ForeignKey(Classification, on_delete=models.CASCADE, null=True, blank=True)
    image_asset_id = models.CharField(max_length=255, null=True, blank=True)
    is_row = models.BooleanField(default=None, null=True, blank=True)
    is_column = models.BooleanField(default=None, null=True, blank=True)
    ending_option = models.BooleanField(default=None, null=True, blank=True, verbose_name=_("Ending Option"))
    order = models.IntegerField(default=1)

    def save(self, *args, **kwargs):
        if not self.pk:
            self.order = self.schema.options.count() + 1
        super().save(*args, **kwargs)


class Recommendation(HasSoftDelete):
    class Meta:
        ordering = ["created_at"]
        verbose_name = _("Recommendation")
        verbose_name_plural = _("Recommendations")

    description = models.TextField()
    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name="recommendations", null=True, blank=True)
    option = models.ForeignKey(
        AnswerSchemaOption,
        on_delete=models.CASCADE,
        related_name="option_recommendations",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_created=True, default=now, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    def __str__(self):
        return self.description


@receiver(post_save, sender=Section)
def _create_section_first_question(sender, instance: Section, created: bool, **kwargs):
    if created:
        instance.questions.create(survey_id=instance.survey_id)


@receiver(post_save, sender=Question)
def _create_answer_schema_for_new_question(sender, instance: Question, created: bool, **kwargs):
    if created:
        AnswerSchema.objects.create(
            survey_id=instance.survey_id,
            section_id=instance.section_id,
            type=instance.type,
            question=instance,
            with_file=instance.type in [instance.QUESTION_TYPE_RADIO_MCQ, instance.QUESTION_TYPE_CHECKBOX_MCQ],
            is_mcq=instance.type
            in [
                instance.QUESTION_TYPE_RADIO_MCQ,
                instance.QUESTION_TYPE_CHECKBOX_MCQ,
                instance.QUESTION_TYPE_DROPDOWN_MCQ,
            ],
            is_grid=instance.type in [instance.QUESTION_TYPE_RADIO_GRID, instance.QUESTION_TYPE_CHECKBOX_GRID],
        )


@receiver(post_save, sender=AnswerSchema)
def _create_answer_schema_first_option(sender, instance: AnswerSchema, created: bool, **kwargs):
    if not created:
        return

    if instance.type in [
        Question.QUESTION_TYPE_RADIO_MCQ,
        Question.QUESTION_TYPE_CHECKBOX_MCQ,
        Question.QUESTION_TYPE_DROPDOWN_MCQ,
    ]:
        survey = instance.survey
        if survey.use_classifications and survey.create_option_for_each_classification:
            for classification in survey.classifications.all():
                instance.options.create(
                    text=classification.name,
                    score=classification.score if survey.use_score else None,
                    classification=classification,
                    survey_id=instance.survey_id,
                    section_id=instance.section_id,
                    question_id=instance.question_id,
                )
        else:
            instance.options.create(
                survey_id=instance.survey_id,
                section_id=instance.section_id,
                question_id=instance.question_id,
            )
        return

    if instance.type in [Question.QUESTION_TYPE_RADIO_GRID, Question.QUESTION_TYPE_CHECKBOX_GRID]:
        instance.options.create(
            survey_id=instance.survey_id,
            section_id=instance.section_id,
            question_id=instance.question_id,
            is_column=False,
            is_row=True,
        )
        instance.options.create(
            survey_id=instance.survey_id,
            section_id=instance.section_id,
            question_id=instance.question_id,
            is_column=True,
            is_row=False,
        )


@receiver(post_save, sender=Section)
@receiver(post_delete, sender=Section)
def _update_sections_order(sender, instance: Section, **kwargs):
    sections = Section.objects.filter(survey_id=instance.survey_id).order_by("order", "id")
    sections_order = list(sections.values_list("order", flat=True))

    if all(order == idx + 1 for idx, order in enumerate(sections_order)):
        return

    for idx, section in enumerate(sections):
        section.order = idx + 1
    Section.objects.bulk_update(sections, ["order"])


@receiver(post_save, sender=Question)
@receiver(post_delete, sender=Question)
def _update_question_order(sender, instance: Question, **kwargs):
    questions = Question.objects.filter(section_id=instance.section_id).order_by("order", "id")
    questions_order = list(questions.values_list("order", flat=True))

    if all(order == idx + 1 for idx, order in enumerate(questions_order)):
        return

    for idx, question in enumerate(questions):
        question.order = idx + 1
    Question.objects.bulk_update(questions, ["order"])


# NOTE: The rest of this file contains legacy (monolith) Django models that
# depend on apps/modules not installed in this service. We keep the source here
# for upcoming restructuring work, but we intentionally prevent Django from
# importing/executing it.
LEGACY_MODELS_SOURCE = r"""

from django.conf import settings
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.timezone import now
from django.utils.translation import gettext as _
from django_soft_delete.models import HasSoftDelete
from model_status.models import HasStatus, Status

from apps.blogs.models import Blog
from apps.classifications.models import ModelTag, Category, HasClassifications
from apps.courses.models import Course
from apps.main.models import HasContent
from apps.payments.models import HasPayment
from apps.sponsors.models import Sponsor, HasSponsor
from apps.threads.models import Thread
from apps.users.models import User
from dj_site_settings.utils import get_setting
from media_library.models import HasMedia
from modules.identity.children.models import Child


class Assessment(HasSponsor, HasSoftDelete, HasMedia, HasPayment, HasClassifications, HasStatus):
    STATUS_CHOICES = (
        Status.STATUS_DRAFT_CHOICE,
        Status.STATUS_PENDING_CHOICE,
        Status.STATUS_PUBLISHED_CHOICE,
        Status.STATUS_SUSPENDED_CHOICE
    )

    DISPLAY_OPTION_SINGLE_QUESTION = 'single_question'
    DISPLAY_OPTION_LIST = 'list'
    DISPLAY_OPTION_NORMAL_FORM = 'normal_form'
    DISPLAY_OPTIONS = (
        (DISPLAY_OPTION_SINGLE_QUESTION, _("Single Question")),
        (DISPLAY_OPTION_LIST, _("List")),
        (DISPLAY_OPTION_NORMAL_FORM, _("Normal Form")),
    )

    ASSESSMENT_TYPE_SURVEY = "survey"
    ASSESSMENT_TYPE_QUESTIONNAIRE = "questionnaire"
    ASSESSMENT_TYPE_CURRICULUM = "curriculum"
    ASSESSMENT_TYPE_EXAM = "exam"
    ASSESSMENT_TYPE_SMART_FORM = "smart_form"
    ASSESSMENT_TYPES = (
        (ASSESSMENT_TYPE_SURVEY, _('Survey')),
        (ASSESSMENT_TYPE_QUESTIONNAIRE, _('Questionnaire')),
        (ASSESSMENT_TYPE_CURRICULUM, _('Curriculum')),
        (ASSESSMENT_TYPE_EXAM, _('Exam')),
        (ASSESSMENT_TYPE_SMART_FORM, _('Smart Form')),
    )

    EVALUATION_TYPE_AUTOMATIC_EVALUATION = 'automatic_evaluation'
    EVALUATION_TYPE_MANUAL_EVALUATION = 'manual_evaluation'
    EVALUATION_TYPES = (
        (EVALUATION_TYPE_AUTOMATIC_EVALUATION, _('Automatic Evaluation')),
        (EVALUATION_TYPE_MANUAL_EVALUATION, _("Manual Evaluation"))
    )

    SEARCH_INDEX = ('title', 'description', 'short_description', 'category__name', 'sponsor__title')

    def get_upload_cover(self, filename):
        return 'assessments/{}/{}'.format(self.id, filename)

    class Meta:
        ordering = ['-created_at']

    title = models.CharField(max_length=255, null=True, blank=True, verbose_name=_("Title"))
    description = models.TextField(null=True, blank=True, verbose_name=_('Description'))
    short_description = models.CharField(max_length=300, null=True, blank=True, verbose_name=_("Short Description"))
    language = models.CharField(max_length=64, choices=settings.LANGUAGES,
                                default=settings.LANGUAGE_CODE, null=True, blank=True, verbose_name=_("Language"))
    status = models.CharField(max_length=64, choices=STATUS_CHOICES, default=Status.STATUS_DRAFT,
                              verbose_name=_("Status"))
    assessment_type = models.CharField(max_length=255, choices=ASSESSMENT_TYPES, default=ASSESSMENT_TYPE_SURVEY,
                                       verbose_name=_("Assessment Type"))
    display_option = models.CharField(max_length=255, choices=DISPLAY_OPTIONS, default=DISPLAY_OPTION_SINGLE_QUESTION,
                                      verbose_name=_("Display Option"))
    is_timed = models.BooleanField(default=False, verbose_name=_("Is Timed"))

    # TODO: rename to is_for_child
    is_for_child = models.BooleanField(default=False, verbose_name=_("Assignable to User"))

    # evaluation settings
    is_evaluable = models.BooleanField(default=False, verbose_name=_("Is Evaluable"))
    evaluation_type = models.CharField(max_length=255, choices=EVALUATION_TYPES,
                                       default=EVALUATION_TYPE_AUTOMATIC_EVALUATION, null=True, blank=True,
                                       verbose_name=_("Evaluation Type"))
    use_score = models.BooleanField(default=True, verbose_name=_("Use Score"))
    use_classifications = models.BooleanField(default=False, verbose_name=_("Use Classifications"))
    use_recommendations = models.BooleanField(default=False, verbose_name=_("Use Recommendations"))
    use_actions = models.BooleanField(default=False, verbose_name=_("Use Actions"))
    allow_end_based_on_answer_repeat = models.BooleanField(default=False, verbose_name=_(
        "Allow Ending Based on Repeating Answer"))
    answers_count_to_end = models.IntegerField(default=0, verbose_name=_("Answers Count to End"))
    end_based_on_answer_repeat_in_row = models.BooleanField(default=False,
                                                            verbose_name=_('End Based on Repeating Answer in Row'))
    allow_update_answer_options_scores_based_on_classification = models.BooleanField(
        default=False,
        verbose_name=_('Allow Update Answer Options Scores Based on Classification'))
    allow_update_answer_options_text_based_on_classification = models.BooleanField(
        default=False,
        verbose_name=_('Allow Update Answer Options Text Based on Classification'))
    create_option_for_each_classification = models.BooleanField(
        default=False,
        verbose_name=_('Create Option for Each Classification'))
    # timestamps
    created_at = models.DateTimeField(auto_created=True, default=now, blank=True, verbose_name=_("Created At"))
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True, verbose_name=_("Updated At"))

    # relationships
    # Course or Curriculum
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey()

    def __str__(self):
        return str(self.title)

    def register_media_collections(self):
        if self.assessment_type == Assessment.ASSESSMENT_TYPE_QUESTIONNAIRE:
            self.register_media_collection(
                single_file=True,
                collection_name='cover',
                description=_('Cover'),
                allowed_mime_types=['image/bmp', 'image/jpeg', 'image/jpg', 'image/png'],
                fallback=get_setting('assessments_details_default_cover'))
            self.register_media_collection(
                collection_name='thumb',
                display_name=_('Thumbnail'),
                allowed_mime_types=['image/bmp', 'image/jpeg', 'image/jpg', 'image/png'],
                fallback=get_setting('assessments_default_thumbnail'))
        elif self.assessment_type == Assessment.ASSESSMENT_TYPE_SURVEY:
            self.register_media_collection(
                single_file=True,
                collection_name='cover',
                description=_('Cover'),
                allowed_mime_types=['image/bmp', 'image/jpeg', 'image/jpg', 'image/png'],
                fallback=get_setting('assessments_details_default_cover'))

            self.register_media_collection(
                single_file=True,
                collection_name='thumb',
                display_name=_('Thumbnail'),
                allowed_mime_types=['image/bmp', 'image/jpeg', 'image/jpg', 'image/png'],
                fallback=get_setting('assessments_details_default_cover'))
        elif self.assessment_type == Assessment.ASSESSMENT_TYPE_CURRICULUM:
            self.register_media_collection(
                single_file=True,
                collection_name='cover',
                description=_('Cover'),
                allowed_mime_types=['image/bmp', 'image/jpeg', 'image/jpg', 'image/png'],
                fallback=get_setting('curriculum_details_default_cover'))
            self.register_media_collection(
                collection_name='thumb',
                display_name=_('Thumbnail'),
                allowed_mime_types=['image/bmp', 'image/jpeg', 'image/jpg', 'image/png'],
                fallback=get_setting('curriculum_default_thumbnail'))

        elif self.assessment_type == Assessment.ASSESSMENT_TYPE_SMART_FORM:
            self.register_media_collection(
                single_file=True,
                collection_name='cover',
                description=_('Cover'),
                allowed_mime_types=['image/bmp', 'image/jpeg', 'image/jpg', 'image/png'],
                fallback=get_setting('smart_form_details_default_cover'))
            self.register_media_collection(
                collection_name='thumb',
                display_name=_('Thumbnail'),
                allowed_mime_types=['image/bmp', 'image/jpeg', 'image/jpg', 'image/png'],
                fallback=get_setting('smart_form_default_thumbnail'))

    @property
    def get_media(self):
        cover = self.cover.url
        # thumb = self.thumb.url

        if self.cover:
            return self.cover.url
        else:
            if self.assessment_type == self.ASSESSMENT_TYPE_CURRICULUM:
                return get_setting('curriculum_default_thumbnail')

            elif self.assessment_type == self.ASSESSMENT_TYPE_SURVEY:
                return get_setting('survey_default_thumbnail')

            elif self.assessment_type == self.ASSESSMENT_TYPE_QUESTIONNAIRE:
                return get_setting('assessments_default_thumbnail')

    @property
    def get_language(self):
        return dict(settings.LANGUAGES).get(self.language)

    @property
    def get_status(self):
        return dict(self.STATUS_CHOICES).get(self.status)

    @property
    def get_evaluation_type(self):
        return dict(self.EVALUATION_TYPES).get(self.evaluation_type)

    @property
    def get_assessment_type(self):
        return dict(self.ASSESSMENT_TYPES).get(self.assessment_type)

    @property
    def get_model_name(self):
        return self.get_assessment_type

    @property
    def get_display_option(self):
        return dict(self.DISPLAY_OPTIONS).get(self.display_option)

    def get_absolute_url(self):
        return reverse('site:assessments:details', args=[self.id])

    @property
    def get_edit_url(self):
        if self.assessment_type in [self.ASSESSMENT_TYPE_CURRICULUM, self.ASSESSMENT_TYPE_EXAM]:
            return reverse('admin:assessments:edit-related', args=[
                self.content_type.app_label, self.content_type.model, self.object_id, self.assessment_type, self.id])
        return reverse('admin:assessments:edit', args=[self.assessment_type, self.id])

    @property
    def get_details_url(self):
        return reverse('admin:assessments:details', args=[self.assessment_type, self.id])

    @property
    def get_delete_url(self):
        return reverse('admin:assessments:delete', args=[self.assessment_type, self.pk])


class Survey(Assessment):
    from apps.assessments.managers import SurveyManager
    objects = SurveyManager()

    class Meta:
        proxy = True
        verbose_name = _("Survey")
        verbose_name_plural = _("Surveys")

    def register_media_collections(self):
        self.register_media_collection(
            single_file=True,
            collection_name='cover',
            description=_('Cover'),
            allowed_mime_types=['image/bmp', 'image/jpeg', 'image/jpg', 'image/png'],
            fallback=get_setting('assessments_details_default_cover'))

        self.register_media_collection(
            single_file=True,
            collection_name='thumb',
            display_name=_('Thumbnail'),
            allowed_mime_types=['image/bmp', 'image/jpeg', 'image/jpg', 'image/png'],
            fallback=get_setting('assessments_details_default_cover'))


class Exam(Assessment):
    from apps.assessments.managers import ExamManager
    objects = ExamManager()

    class Meta:
        proxy = True


class Curriculum(Assessment):
    from apps.assessments.managers import CurriculumManager
    objects = CurriculumManager()

    class Meta:
        proxy = True
        verbose_name = _("Curriculum")
        verbose_name_plural = _("Curricula")

    def register_media_collections(self):
        self.register_media_collection(
            single_file=True,
            collection_name='cover',
            description=_('Cover'),
            allowed_mime_types=['image/bmp', 'image/jpeg', 'image/jpg', 'image/png'],
            fallback=get_setting('curriculum_details_default_cover'))

        self.register_media_collection(
            single_file=True,
            collection_name='thumb',
            display_name=_('Thumbnail'),
            allowed_mime_types=['image/bmp', 'image/jpeg', 'image/jpg', 'image/png'],
            fallback=get_setting('curriculum_default_thumbnail'))


class Questionnaire(Assessment):
    from apps.assessments.managers import QuestionnaireManager
    objects = QuestionnaireManager()

    class Meta:
        proxy = True
        verbose_name = _("Questionnaire")
        verbose_name_plural = _("Questionnaires")

    def register_media_collections(self):
        self.register_media_collection(
            single_file=True,
            collection_name='cover',
            description=_('Cover'),
            allowed_mime_types=['image/bmp', 'image/jpeg', 'image/jpg', 'image/png'],
            fallback=get_setting('assessments_details_default_cover'))

        self.register_media_collection(
            single_file=True,
            collection_name='thumb',
            display_name=_('Thumbnail'),
            allowed_mime_types=['image/bmp', 'image/jpeg', 'image/jpg', 'image/png'],
            fallback=get_setting('assessments_default_thumbnail'))


class SmartForm(Assessment):
    from apps.assessments.managers import SmartFormManager
    objects = SmartFormManager()

    class Meta:
        proxy = True
        verbose_name = _("Smart Form")
        verbose_name_plural = _("Smart Forms")

    def register_media_collections(self):
        self.register_media_collection(
            single_file=True,
            collection_name='cover',
            description=_('Cover'),
            allowed_mime_types=['image/bmp', 'image/jpeg', 'image/jpg', 'image/png'],
            fallback=get_setting('smart_form_details_default_cover'))

        self.register_media_collection(
            single_file=True,
            collection_name='thumb',
            display_name=_('Thumbnail'),
            allowed_mime_types=['image/bmp', 'image/jpeg', 'image/jpg', 'image/png'],
            fallback=get_setting('smart_form_default_thumbnail'))


class Action(models.Model):
    class Meta:
        ordering = ['id']

    title = models.CharField(max_length=255, null=True, blank=True, default=None, verbose_name=_("Title"))
    description = models.TextField(null=True, blank=True, default=None, verbose_name=_('Description'))
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name='actions')
    upper_limit = models.FloatField(default=0, verbose_name=_("Upper Limit"))
    lower_limit = models.FloatField(default=0, verbose_name=_("Lower Limit"))

    @property
    def get_edit_url(self):
        return reverse('admin:assessments:actions:edit',
                       args=[self.assessment.assessment_type, self.assessment_id, self.id])

    @property
    def get_delete_url(self):
        return reverse('admin:assessments:actions:delete', args=[
            self.assessment.assessment_type, self.assessment_id, self.id
        ])


class RecommendedMaterial(models.Model):
    action = models.ForeignKey(Action, on_delete=models.CASCADE, related_name='recommended_materials')
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey()


class Classification(HasSoftDelete):
    class Meta:
        verbose_name = _("Classification")
        verbose_name_plural = _("Classifications")
        ordering = ['created_at']

    name = models.CharField(max_length=255, null=True, blank=True)
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name='classifications', null=True,
                                   blank=True)
    score = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_created=True, default=now, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    def __str__(self):
        return self.name

    @property
    def get_edit_url(self):
        return reverse('admin:assessments:classifications:update',
                       args=[self.assessment.assessment_type, self.assessment_id, self.id])

    @property
    def get_delete_url(self):
        return reverse("admin:assessments:classifications:delete", args=[
            self.assessment.assessment_type, self.assessment_id, self.pk
        ])


class Section(models.Model):
    SUBMIT_ACTION_NEXT = "next"
    SUBMIT_ACTION_SUBMIT = "submit"
    SUBMIT_ACTION_JUMP = "jump"
    SUBMIT_ACTIONS = (
        (SUBMIT_ACTION_NEXT, _("Next Section")),
        (SUBMIT_ACTION_SUBMIT, _("Submit")),
        (SUBMIT_ACTION_JUMP, _("To section {section}"))
    )

    def get_upload_cover(self, filename):
        return 'assessments/{}/sections/{}/{}'.format(self.assessment_id, self.id, filename)

    class Meta:
        ordering = ['order']

    title = models.CharField(max_length=255, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name="sections")
    order = models.IntegerField(default=1, null=True, blank=True)
    is_hidden = models.BooleanField(default=False)
    cover = models.ImageField(null=True, blank=True, upload_to=get_upload_cover)
    submit_action = models.CharField(max_length=90, choices=SUBMIT_ACTIONS, default=SUBMIT_ACTION_NEXT)
    submit_action_target = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True)
    deleted_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_created=True, default=now, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    @property
    def get_edit_url(self):
        return reverse('admin:assessments:sections:edit',
                       args=[self.assessment.assessment_type, self.assessment_id, self.id])

    @property
    def get_delete_url(self):
        return reverse("admin:assessments:sections:delete", args=[
            self.assessment.assessment_type, self.assessment_id, self.id
        ])


class Question(models.Model):
    QUESTION_TYPE_TEXT = 'text'
    QUESTION_TYPE_TEXTAREA = 'textarea'
    QUESTION_TYPE_NUMBER = 'number'
    QUESTION_TYPE_FILE = 'file'
    QUESTION_TYPE_DATE = 'date'
    QUESTION_TYPE_TIME = 'time'
    QUESTION_TYPE_DATETIME = 'datetime'
    QUESTION_TYPE_RADIO_MCQ = 'radio'
    QUESTION_TYPE_CHECKBOX_MCQ = 'checkbox'
    QUESTION_TYPE_DROPDOWN_MCQ = 'dropdown'
    QUESTION_TYPE_RADIO_GRID = 'radio_grid'
    QUESTION_TYPE_CHECKBOX_GRID = 'checkbox_grid'
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
        (QUESTION_TYPE_CHECKBOX_GRID, _("Checkbox Grid Answer"))
    )

    def get_upload_cover(self, filename):
        return 'assessments/{}/sections/{}/questions/{}/{}'.format(
            self.assessment_id, self.section_id, self.id, filename)

    class Meta:
        ordering = ['section__order', 'order']

    title = models.CharField(max_length=255, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    answer_time = models.DurationField(verbose_name=_("Answer Time"), null=True, blank=True)
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name="questions", null=True,
                                   blank=True)
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name="questions", null=True, blank=True)

    order = models.IntegerField(default=1, null=True, blank=True)
    is_required = models.BooleanField(default=False)
    type = models.CharField(max_length=100, choices=QUESTION_TYPE_CHOICES, default=QUESTION_TYPE_RADIO_MCQ,
                            null=True, blank=True)
    cover = models.ImageField(null=True, blank=True, upload_to=get_upload_cover)

    deleted_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_created=True, default=now, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    @property
    def mcq_types(self):
        return [self.QUESTION_TYPE_RADIO_MCQ, self.QUESTION_TYPE_CHECKBOX_MCQ, self.QUESTION_TYPE_DROPDOWN_MCQ]

    @property
    def grid_types(self):
        return [self.QUESTION_TYPE_RADIO_GRID, self.QUESTION_TYPE_CHECKBOX_GRID]

    @property
    def get_edit_url(self):
        return reverse('admin:assessments:sections:questions:edit',
                       args=[self.assessment.assessment_type, self.assessment_id, self.section_id, self.id])

    @property
    def get_delete_url(self):
        return reverse('admin:assessments:sections:questions:delete', args=[
            self.assessment.assessment_type, self.assessment_id, self.section_id, self.pk
        ])

    def update_answer_schema(self):
        if self.type not in self.mcq_types and self.type not in self.grid_types:
            self.answer_schema.type = self.type
            self.answer_schema.with_file = False
            self.answer_schema.is_mcq = False
            self.answer_schema.is_grid = False
            self.answer_schema.save()
            self.answer_schema.options.all().delete()
        elif self.type in self.mcq_types:
            if not self.answer_schema.is_mcq:
                self.answer_schema.options.all().delete()
            self.answer_schema.type = self.type
            self.answer_schema.with_file = self.type != self.QUESTION_TYPE_DROPDOWN_MCQ
            self.answer_schema.is_mcq = True
            self.answer_schema.is_grid = False
            self.answer_schema.save()
            if self.answer_schema.options.count() == 0:
                if self.assessment.is_evaluable and self.assessment.use_classifications:
                    order = 0
                    for classification in self.assessment.classifications.all():
                        self.answer_schema.options.create(
                            assessment=self.assessment,
                            section=self.section,
                            question=self,
                            text=classification.name,
                            score=classification.score if self.assessment.use_score else None,
                            classification=classification,
                            order=order)
                        order += 1
                else:
                    self.answer_schema.options.create(
                        assessment=self.assessment,
                        section=self.section,
                        question=self)
            else:
                if self.type == self.QUESTION_TYPE_DROPDOWN_MCQ:
                    for option in self.answer_schema.options.all():
                        option.image.delete()
                        option.save()
        elif self.type in self.grid_types:
            if not self.answer_schema.is_grid:
                self.answer_schema.options.all().delete()
            self.answer_schema.type = self.type
            self.answer_schema.with_file = False
            self.answer_schema.is_mcq = False
            self.answer_schema.is_grid = True
            self.answer_schema.save()
            if self.answer_schema.options.count() == 0:
                self.answer_schema.options.create(
                    assessment=self.assessment,
                    section=self.section,
                    question=self,
                    is_row=True,
                    is_column=False)
                self.answer_schema.options.create(
                    assessment=self.assessment,
                    section=self.section,
                    question=self,
                    is_row=False,
                    is_column=True)

    def save(self, *args, **kwargs):
        if not self.pk:
            self.order = self.section.questions.count() + 1
        super(Question, self).save(*args, **kwargs)


class AnswerSchema(models.Model):
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE)
    section = models.ForeignKey(Section, on_delete=models.CASCADE)
    question = models.OneToOneField(Question, on_delete=models.CASCADE, related_name="answer_schema")
    type = models.CharField(max_length=100, choices=Question.QUESTION_TYPE_CHOICES,
                            default=Question.QUESTION_TYPE_RADIO_MCQ)
    with_file = models.BooleanField(default=False)
    is_mcq = models.BooleanField(default=False)
    is_grid = models.BooleanField(default=False)


class AnswerSchemaOption(models.Model):
    def get_upload_image(self, filename):
        return 'images/assessments/{}/sections/{}/questions/{}/options/option-{}-{}'.format(
            self.assessment_id, self.section_id, self.question_id, self.id, filename)

    class Meta:
        ordering = ['order']

    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE)
    section = models.ForeignKey(Section, on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    schema = models.ForeignKey(AnswerSchema, on_delete=models.CASCADE, related_name="options")
    text = models.TextField(null=True, blank=True)
    score = models.IntegerField(default=None, null=True, blank=True)
    classification = models.ForeignKey('Classification', on_delete=models.CASCADE, null=True, blank=True)
    image = models.FileField(null=True, blank=True, upload_to=get_upload_image)
    is_row = models.BooleanField(default=None, null=True, blank=True)
    is_column = models.BooleanField(default=None, null=True, blank=True)
    ending_option = models.BooleanField(default=None, null=True, blank=True, verbose_name=_("Ending Option"))
    order = models.IntegerField(default=1)

    @property
    def get_edit_url(self):
        return reverse('admin:assessments:sections:questions:options:edit',
                       args=[self.assessment.assessment_type, self.assessment_id, self.section_id, self.question_id,
                             self.id])

    @property
    def get_delete_url(self):
        return reverse('admin:assessments:sections:questions:options:delete', args=[
            self.assessment.assessment_type, self.assessment_id, self.section_id, self.question_id,
            self.id
        ])

    def save(self, *args, **kwargs):
        if not self.pk:
            self.order = self.schema.options.count() + 1
        super(AnswerSchemaOption, self).save(*args, **kwargs)


class Recommendation(HasSoftDelete):
    class Meta:
        verbose_name = _("Recommendation")
        verbose_name_plural = _("Recommendations")
        ordering = ['created_at']

    description = models.TextField()
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name='recommendations', null=True,
                                   blank=True)
    option = models.ForeignKey(AnswerSchemaOption, on_delete=models.CASCADE, related_name="option_recommendations",
                               null=True, blank=True)
    created_at = models.DateTimeField(auto_created=True, default=now, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    def __str__(self):
        return mark_safe(self.description)

    @property
    def get_delete_url(self):
        return reverse("admin:assessments:sections:questions:options:recommendations:delete", args=[
            self.assessment.assessment_type, self.assessment_id,
            self.option.section_id, self.option.question_id, self.option_id, self.pk
        ])


class UserAssessment(HasPayment):
    class Meta:
        ordering = ['submitted_at']

    is_paid = models.BooleanField(default=False)
    assessment = models.ForeignKey(Assessment, on_delete=models.SET_NULL, null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    child = models.ForeignKey(Child, on_delete=models.SET_NULL, related_name="child_assessments", null=True,
                              blank=True)
    count_of_ending_options = models.IntegerField(default=0)
    evaluated_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    score = models.IntegerField(null=True, blank=True)
    progress = models.IntegerField(null=True, blank=True, default=0)
    last_question = models.ForeignKey(Question, on_delete=models.CASCADE, null=True, blank=True)
    classifications = models.ManyToManyField('Classification', through='UserAssessmentClassification')
    recommendations = models.ManyToManyField('Recommendation', through='UserAssessmentRecommendation')
    action = models.ForeignKey('Action', on_delete=models.SET_NULL, null=True, blank=True)


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
        ordering = ['question__section__order', 'question__order']

    assessment = models.ForeignKey(Assessment, on_delete=models.SET_NULL, null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    question = models.ForeignKey(Question, on_delete=models.SET_NULL, null=True,
                                 blank=True)
    question_title = models.CharField(max_length=255, null=True)
    user_assessment = models.ForeignKey(UserAssessment, on_delete=models.CASCADE, null=True, blank=True)
    answer = models.TextField(default=None, blank=True, null=True)
    type = models.CharField(max_length=50, choices=Question.QUESTION_TYPE_CHOICES,
                            default=Question.QUESTION_TYPE_RADIO_MCQ)
    selected_options = models.ManyToManyField(AnswerSchemaOption)
    score = models.IntegerField(null=True, blank=True)
    order = models.IntegerField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if self.question:
            self.question_title = self.question.title
        super(UserAnswer, self).save(*args, **kwargs)


@receiver(post_save, sender=Section)
def create_section_first_questions(sender, instance, created, **kwargs):
    if created:
        instance.questions.create(assessment_id=instance.assessment_id)


@receiver(post_save, sender=Question)
def create_answer_schema_for_new_question(sender, instance, created, **kwargs):
    if created:
        AnswerSchema.objects.create(
            assessment_id=instance.assessment_id,
            section_id=instance.section_id,
            type=instance.type,
            question=instance,
            with_file=instance.type in [instance.QUESTION_TYPE_RADIO_MCQ, instance.QUESTION_TYPE_CHECKBOX_MCQ],
            is_mcq=instance.type in [instance.QUESTION_TYPE_RADIO_MCQ, instance.QUESTION_TYPE_CHECKBOX_MCQ,
                                     instance.QUESTION_TYPE_DROPDOWN_MCQ],
            is_grid=instance.type in [instance.QUESTION_TYPE_RADIO_GRID, instance.QUESTION_TYPE_CHECKBOX_GRID])


@receiver(post_save, sender=AnswerSchema)
def create_answer_schema_first_option(sender, instance, created, **kwargs):
    if created:
        if instance.type in [Question.QUESTION_TYPE_RADIO_MCQ, Question.QUESTION_TYPE_CHECKBOX_MCQ,
                             Question.QUESTION_TYPE_DROPDOWN_MCQ]:
            if instance.assessment.use_classifications and instance.assessment.create_option_for_each_classification:
                for classification in instance.assessment.classifications.all():
                    instance.options.create(
                        text=classification.name,
                        score=classification.score if instance.assessment.use_score else None,
                        classification=classification,
                        assessment_id=instance.assessment_id,
                        section_id=instance.section_id,
                        question_id=instance.question_id)
            else:
                instance.options.create(
                    assessment_id=instance.assessment_id,
                    section_id=instance.section_id,
                    question_id=instance.question_id)

        elif instance.type in [Question.QUESTION_TYPE_RADIO_GRID, Question.QUESTION_TYPE_CHECKBOX_GRID]:
            instance.options.create(
                assessment_id=instance.assessment_id,
                section_id=instance.section_id,
                question_id=instance.question_id,
                is_column=False,
                is_row=True)
            instance.options.create(
                assessment_id=instance.assessment_id,
                section_id=instance.section_id,
                question_id=instance.question_id,
                is_column=True,
                is_row=False)


@receiver(post_save, sender=Section)
@receiver(post_delete, sender=Section)
def update_sections_order(sender, instance, **kwargs):
    sections = Section.objects.filter(assessment_id=instance.assessment_id)
    sections_order = sections.values_list('order', flat=True)

    if not all([i == count + 1 for count, i in enumerate(sections_order)]):
        for count, section in enumerate(sections):
            section.order = count + 1
        Section.objects.bulk_update(sections, ['order'])


@receiver(post_save, sender=Question)
@receiver(post_delete, sender=Question)
def update_question_order(sender, instance, **kwargs):
    questions = Question.objects.filter(section_id=instance.section_id)
    questions_order = questions.values_list('order', flat=True)

    if not all([i == count + 1 for count, i in enumerate(questions_order)]):
        for count, question in enumerate(questions):
            question.order = count + 1

        Question.objects.bulk_update(questions, ['order'])


@receiver(post_save, sender=UserAssessment)
def create_user_assessment_tree(sender, instance, created, **kwargs):
    if created:
        assessment = instance.assessment
        i = 1
        for question in assessment.questions.all():
            UserAnswer.objects.create(
                user=instance.user,
                question=question,
                question_title=question.title,
                assessment=instance.assessment,
                user_assessment=instance,
                type=question.type,
                order=i
            )
            i += 1
"""
