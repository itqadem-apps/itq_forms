from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from survey_collections.models import SurveyCollection
from surveys.models import Survey

from .models import Price


def backfill_zero_prices(*, survey=None, collection=None) -> None:
    currencies = getattr(settings, "AVAILABLE_CURRENCIES", []) or []
    if not currencies:
        return

    qs = Price.objects.filter(survey=survey, collection=collection)
    existing = set(qs.values_list("currency", flat=True))

    missing = [c for c in currencies if c and c not in existing]
    if not missing:
        return

    Price.objects.bulk_create(
        [
            Price(survey=survey, collection=collection, currency=currency, amount_cents=0)
            for currency in missing
        ]
    )


@receiver(post_save, sender=Survey)
def _backfill_survey_zero_prices(sender, instance: Survey, **kwargs):
    backfill_zero_prices(survey=instance)


@receiver(post_save, sender=SurveyCollection)
def _backfill_collection_zero_prices(sender, instance: SurveyCollection, **kwargs):
    backfill_zero_prices(collection=instance)
