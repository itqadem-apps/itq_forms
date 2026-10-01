from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from survey_collections.models import SurveyCollection
from surveys.models import Survey

from .currency import SHOP_CURRENCY
from .models import Price


def backfill_zero_prices(*, survey=None, collection=None) -> None:
    # A deployed AVAILABLE_CURRENCIES may still list USD/EUR/SAR; padding those
    # would recreate the rows the EGP-only migration removed (estate:AD-17).
    if not getattr(settings, "AVAILABLE_CURRENCIES", None):
        return

    qs = Price.objects.filter(survey=survey, collection=collection, currency=SHOP_CURRENCY)
    if qs.exists():
        return

    Price.objects.create(
        survey=survey, collection=collection, currency=SHOP_CURRENCY, amount_cents=0
    )


@receiver(post_save, sender=Survey)
def _backfill_survey_zero_prices(sender, instance: Survey, **kwargs):
    backfill_zero_prices(survey=instance)


@receiver(post_save, sender=SurveyCollection)
def _backfill_collection_zero_prices(sender, instance: SurveyCollection, **kwargs):
    backfill_zero_prices(collection=instance)
