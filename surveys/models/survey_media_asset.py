from uuid import uuid4

from django.db import models
from django.utils.translation import gettext_lazy as _

from .survey import Survey


class AssetType(models.TextChoices):
    COVER = "cover", _("Cover")
    THUMBNAIL = "thumbnail", _("Thumbnail")
    ATTACHMENT = "attachment", _("Attachment")


class SurveyMediaAsset(models.Model):
    class Meta:
        indexes = [
            models.Index(fields=["survey"], name="ix_survey_media_assets_survey"),
        ]

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name="assets")
    asset_id = models.CharField(max_length=255)
    asset_type = models.CharField(max_length=32, choices=AssetType.choices)
