"""estate:AD-17 — surveys and collections are priced in EGP only."""
from collections import Counter
from importlib import import_module
from types import SimpleNamespace

import pytest
from django.apps import apps
from django.db import IntegrityError, transaction

from pricing.inputs import PriceNestedInput
from pricing.models import Price
from pricing.services import upsert_prices_for_parent
from pricing.signals import backfill_zero_prices

egp_only = import_module("pricing.migrations.0005_egp_only")


class _Row(SimpleNamespace):
    def delete(self):
        self.deleted = True

    def save(self):
        self.saved = True


class _Discounts:
    def __init__(self, *discounts):
        self.discounts = list(discounts)

    def filter(self, *, price, type):
        return [d for d in self.discounts if d.price is price and d.type == type]


def _row(pk, currency, amount, compare_at=None):
    return _Row(pk=pk, currency=currency, amount_cents=amount,
                compare_at_amount_cents=compare_at, survey_id=1, collection_id=None,
                deleted=False, saved=False)


def _collapse(*rows, discounts=_Discounts()):
    deleted = Counter()
    keep = egp_only._collapse(list(rows), SimpleNamespace(objects=discounts), deleted)
    return keep, deleted


def test_rate_rounds_up_to_whole_egp():
    # 10 USD / 0.019243 = 519.67 EGP -> 520 EGP
    assert egp_only.to_egp_cents(1000, "USD") == 52000


def test_real_egp_price_is_kept_and_the_rest_deleted():
    egp, usd = _row(1, "EGP", 50000), _row(2, "USD", 1000)
    keep, deleted = _collapse(egp, usd)
    assert keep is egp and keep.amount_cents == 50000
    assert usd.deleted and deleted == {"USD": 1}


def test_egp_zero_padding_beside_a_foreign_price_is_converted_not_free():
    pad, usd, sar = _row(1, "EGP", 0), _row(2, "usd", 1000, 2000), _row(3, "SAR", 0)
    fixed = SimpleNamespace(pk=9, price=usd, type="fixed_amount", value=150, save=lambda **_: None)
    keep, deleted = _collapse(pad, usd, sar, discounts=_Discounts(fixed))
    assert keep is usd and keep.currency == "EGP"
    assert keep.amount_cents == 52000
    assert keep.compare_at_amount_cents == 104000  # 20 USD = 1039.34 -> 1040 EGP
    assert fixed.value == 7700  # 1.50 USD = 77.95 EGP, rounded down
    assert pad.deleted and sar.deleted and deleted == {"EGP": 1, "SAR": 1}


def test_usd_wins_over_other_foreign_prices():
    sar, usd = _row(1, "SAR", 3000), _row(2, "USD", 1000)
    keep, _ = _collapse(sar, usd)
    assert keep is usd


def test_free_item_with_only_zero_rows_stays_free_in_egp():
    usd, sar = _row(1, "USD", 0), _row(2, "SAR", 0)
    keep, _ = _collapse(usd, sar)
    assert keep is usd and keep.currency == "EGP" and keep.amount_cents == 0
    assert sar.deleted


def test_duplicate_egp_rows_keep_the_highest():
    low, high = _row(1, "EGP", 100), _row(2, "EGP", 900)
    keep, deleted = _collapse(low, high)
    assert keep is high and low.deleted and deleted == {"EGP": 1}


def test_unknown_priced_currency_aborts_instead_of_going_free():
    with pytest.raises(RuntimeError, match="no EGP rate"):
        _collapse(_row(1, "EGP", 0), _row(2, "GBP", 1000))


@pytest.mark.django_db
def test_migration_is_a_no_op_on_egp_only_data(survey):
    before = list(Price.objects.values_list("pk", "currency", "amount_cents"))
    egp_only.forwards(apps, None)
    assert list(Price.objects.values_list("pk", "currency", "amount_cents")) == before


@pytest.mark.django_db
def test_database_refuses_a_non_egp_or_second_price(survey):
    with pytest.raises(IntegrityError), transaction.atomic():
        Price.objects.create(survey=survey, currency="USD", amount_cents=100)
    with pytest.raises(IntegrityError), transaction.atomic():
        Price.objects.create(survey=survey, currency="EGP", amount_cents=100)


@pytest.mark.django_db
def test_padding_ignores_foreign_codes_in_a_stale_env(survey, settings):
    settings.AVAILABLE_CURRENCIES = ["EGP", "USD", "SAR"]
    Price.objects.filter(survey=survey).delete()
    backfill_zero_prices(survey=survey)
    assert list(survey.prices.values_list("currency", "amount_cents")) == [("EGP", 0)]


@pytest.mark.django_db
def test_nested_prices_skip_foreign_entries_and_upsert_the_egp_row(survey):
    upsert_prices_for_parent(survey, [
        PriceNestedInput(currency="EGP", amount_cents=50000),
        PriceNestedInput(currency="USD", amount_cents=1000),
        PriceNestedInput(currency="SAR", amount_cents=3700),
    ])
    assert list(survey.prices.values_list("currency", "amount_cents")) == [("EGP", 50000)]


@pytest.mark.django_db
def test_nested_price_without_currency_is_egp(survey):
    upsert_prices_for_parent(survey, [PriceNestedInput(amount_cents=7000)])
    assert list(survey.prices.values_list("currency", "amount_cents")) == [("EGP", 7000)]
