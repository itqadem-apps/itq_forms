from django.contrib.auth import get_user_model
from django.db import models
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _

from surveys.models import Survey
from taxonomy.models import Category

UserModel = get_user_model()


class SurveyCollection(models.Model):
    class Meta:
        verbose_name = _("Survey Collection")
        verbose_name_plural = _("Survey Collections")

    STATUS_DRAFT = "draft"
    STATUS_PENDING = "pending"
    STATUS_PUBLISHED = "published"
    STATUS_ARCHIVED = "archived"
    STATUS_SUSPENDED = "suspended"
    STATUS_CHOICES = (
        (STATUS_DRAFT, _("Draft")),
        (STATUS_PENDING, _("Pending")),
        (STATUS_PUBLISHED, _("Published")),
        (STATUS_ARCHIVED, _("Archived")),
        (STATUS_SUSPENDED, _("Suspended")),
    )

    PRIVACY_PUBLIC = "public"
    PRIVACY_PRIVATE = "private"
    PRIVACY_CHOICES = (
        (PRIVACY_PUBLIC, _("Public")),
        (PRIVACY_PRIVATE, _("Private")),
    )

    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    privacy_status = models.CharField(max_length=32, choices=PRIVACY_CHOICES, null=True, blank=True)
    title = models.CharField(max_length=255, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    short_description = models.CharField(max_length=300, null=True, blank=True)
    slug = models.CharField(max_length=255, null=True, blank=True)
    language = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField(default=now, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    price = models.FloatField(default=0)
    video_list = models.JSONField(null=True, blank=True)
    sponsor = models.PositiveIntegerField(null=True, blank=True)
    type = models.CharField(max_length=255, null=True, blank=True)
    author = models.ForeignKey(UserModel, on_delete=models.SET_NULL, null=True, blank=True)
    subscribers = models.ManyToManyField(
        UserModel,
        related_name="subscribed_collections",
        blank=True,
    )
    enrolled_users = models.ManyToManyField(
        UserModel,
        related_name="enrolled_collections",
        blank=True,
    )
    assessments = models.ManyToManyField(
        Survey,
        related_name="collections",
        blank=True,
        help_text=_("Assessments included in this collection."),
    )
