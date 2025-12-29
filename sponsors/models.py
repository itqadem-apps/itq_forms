from django.db import models
from django.utils.translation import gettext_lazy as _


class Sponsor(models.Model):
    title = models.CharField(max_length=255, verbose_name=_("Title"))
    description = models.TextField(null=True, blank=True, verbose_name=_("Description"))
    cover_asset_id = models.CharField(
        max_length=255, null=True, blank=True, verbose_name=_("Cover (Asset ID)")
    )
    inverted_cover_asset_id = models.CharField(
        max_length=255, null=True, blank=True, verbose_name=_("Inverted Cover (Asset ID)")
    )

    def __str__(self) -> str:
        return self.title

