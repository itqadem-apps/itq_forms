from django.contrib.auth import get_user_model
from django.db import models, transaction
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
    created_at = models.DateTimeField(default=now, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    sponsor = models.PositiveIntegerField(null=True, blank=True)
    type = models.CharField(max_length=255, null=True, blank=True)
    # Media-library asset ids, the same two flat columns a Survey carries
    # (`surveys.Survey.cover_id` / `thumb_id`). A collection used to hold no
    # imagery of its own, so its admin hero and every storefront card rendered
    # the placeholder no matter what its members looked like.
    cover_id = models.CharField(max_length=255, null=True, blank=True)
    thumb_id = models.CharField(max_length=255, null=True, blank=True)
    organization_id = models.UUIDField(
        db_index=True,
        verbose_name=_("Organization ID"),
    )
    assessments = models.ManyToManyField(
        Survey,
        related_name="collections",
        blank=True,
        through="CollectionMembership",
        help_text=_("Assessments included in this collection."),
    )

    def append_member(self, survey):
        """Add `survey` after the existing members; a no-op if it is already one."""
        with transaction.atomic():
            # The same row lock as reorder_collection_surveys, so concurrent appends and saves serialize.
            list(SurveyCollection.objects.select_for_update().filter(pk=self.pk).values_list("pk", flat=True))
            memberships = CollectionMembership.objects.filter(surveycollection=self)
            if memberships.filter(survey=survey).exists():
                return
            last = memberships.aggregate(m=models.Max("order"))["m"]
            CollectionMembership.objects.create(
                surveycollection=self, survey=survey, order=0 if last is None else last + 1
            )

    @property
    def title(self):
        t = self.translations.first()
        return t.title if t else None

    @property
    def language(self):
        t = self.translations.first()
        return t.language if t else None

    def __str__(self):
        return str(self.title or self.pk)


class SurveyCollectionTranslation(models.Model):
    class Meta:
        indexes = [
            models.Index(fields=["collection", "language"], name="ix_survey_col_tr_lang"),
        ]

    collection = models.ForeignKey(
        SurveyCollection,
        on_delete=models.CASCADE,
        related_name="translations",
    )
    language = models.CharField(max_length=64, null=True, blank=True)
    title = models.CharField(max_length=255, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    # TextField, not CharField(300): one legacy collection carries a 355-character
    # short description. Truncating it to fit was the alternative.
    short_description = models.TextField(null=True, blank=True)
    slug = models.CharField(max_length=255, null=True, blank=True)
    seo = models.JSONField(null=True, blank=True)


class CollectionMembership(models.Model):
    """A collection's member, in the order the admin set (report #128).

    Adopts the table Django created for the plain M2M, so the column names are
    the auto-generated ones; migration 0016 added `order` without moving a row.
    """

    surveycollection = models.ForeignKey(
        SurveyCollection, on_delete=models.CASCADE, related_name="memberships"
    )
    survey = models.ForeignKey(
        Survey, on_delete=models.CASCADE, related_name="collection_memberships"
    )
    # db_default: inserts that name only the two ids (the pre-release pod mid-rollout, legacy_load) still succeed.
    order = models.PositiveIntegerField(default=0, db_default=0)

    class Meta:
        db_table = "survey_collections_surveycollection_assessments"
        unique_together = [("surveycollection", "survey")]
