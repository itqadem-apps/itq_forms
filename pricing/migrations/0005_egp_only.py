"""estate:AD-17 — collapse every survey/collection price to one EGP row.

Per parent:
- a real EGP price (non-zero, or every price is zero) is kept; other rows go;
- an EGP 0 beside a positive foreign price is zero-padding, not "free": the
  foreign price is converted instead;
- with no real EGP price, the first positive foreign price (USD, EUR, SAR,
  AED) is converted at the rates below, rounded UP to whole EGP, together with
  its compare-at price and fixed-amount discounts (rounded DOWN, so a discount
  never grows); the other rows go;
- an unknown currency with a positive amount aborts the migration rather than
  leave an item silently free.

Every conversion and per-currency deletion count is logged to the deploy log.
Idempotent: a second run finds only EGP rows and changes nothing. Changed
parents are republished (SurveyUpdated / CollectionUpdated via the outbox) so
orders' purchasable prices refresh.

Rates are fixed at authoring time and never fetched during deploy.
Source: https://open.er-api.com/v6/latest/EGP (exchangerate-api.com),
time_last_update_utc "Thu, 01 Oct 2026 00:02:31 +0000". Units of currency per 1 EGP.
"""
from collections import Counter
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
import logging

from django.db import migrations, models

logger = logging.getLogger("pricing.migrations.egp_only")

SHOP_CURRENCY = "EGP"
PER_EGP = {
    "USD": Decimal("0.019243"),
    "EUR": Decimal("0.016945"),
    "SAR": Decimal("0.072151"),
    "AED": Decimal("0.07066"),
}


def to_egp_cents(cents, currency, rounding=ROUND_CEILING):
    if cents is None:
        return None
    egp = (Decimal(cents) / 100 / PER_EGP[currency]).to_integral_value(rounding=rounding)
    return int(egp) * 100


def _collapse(rows, Discount, deleted):
    """Return the row kept as the parent's EGP price, mutating rows in place."""
    for row in rows:
        row.currency = row.currency.strip().upper()
    egp = [r for r in rows if r.currency == SHOP_CURRENCY]
    foreign = [r for r in rows if r.currency != SHOP_CURRENCY and r.amount_cents > 0]
    best_egp = max(egp, key=lambda r: (r.amount_cents, -r.pk), default=None)

    if best_egp is not None and (best_egp.amount_cents > 0 or not foreign):
        keep = best_egp
    elif foreign:
        unknown = sorted({r.currency for r in foreign} - PER_EGP.keys())
        if unknown:
            raise RuntimeError(f"no EGP rate for {unknown} on price ids {[r.pk for r in foreign]}")
        keep = min(foreign, key=lambda r: list(PER_EGP).index(r.currency))
        old = (keep.currency, keep.amount_cents, keep.compare_at_amount_cents)
        keep.amount_cents = to_egp_cents(keep.amount_cents, keep.currency)
        keep.compare_at_amount_cents = to_egp_cents(keep.compare_at_amount_cents, keep.currency)
        for d in Discount.objects.filter(price=keep, type="fixed_amount"):
            new_value = to_egp_cents(d.value, keep.currency, ROUND_FLOOR)
            logger.info("egp_only discount id=%s %s %s -> EGP %s", d.pk, keep.currency, d.value, new_value)
            d.value = new_value
            d.save(update_fields=["value"])
        logger.info(
            "egp_only convert price id=%s survey=%s collection=%s %s %s (compare_at %s) -> EGP %s (compare_at %s)",
            keep.pk, keep.survey_id, keep.collection_id, old[0], old[1], old[2],
            keep.amount_cents, keep.compare_at_amount_cents,
        )
        keep.currency = SHOP_CURRENCY
    else:
        # Free item carrying only foreign zero rows: keep it free, in EGP.
        keep = rows[0]
        keep.currency = SHOP_CURRENCY

    for row in rows:
        if row is not keep:
            deleted[row.currency] += 1
            row.delete()
    keep.save()
    return keep


def forwards(apps, schema_editor):
    Price = apps.get_model("pricing", "Price")
    Discount = apps.get_model("pricing", "Discount")
    deleted = Counter()
    changed = {"survey": set(), "collection": set()}

    for parent in ("survey", "collection"):
        parent_ids = (
            Price.objects.filter(**{f"{parent}__isnull": False})
            .exclude(currency=SHOP_CURRENCY)
            .values_list(f"{parent}_id", flat=True)
            .distinct()
        )
        dup_egp = (
            Price.objects.filter(**{f"{parent}__isnull": False}, currency=SHOP_CURRENCY)
            .values(f"{parent}_id")
            .annotate(n=models.Count("id"))
            .filter(n__gt=1)
            .values_list(f"{parent}_id", flat=True)
        )
        for parent_id in sorted(set(parent_ids) | set(dup_egp)):
            rows = list(Price.objects.filter(**{f"{parent}_id": parent_id}).order_by("pk"))
            _collapse(rows, Discount, deleted)
            changed[parent].add(parent_id)

    logger.warning(
        "egp_only done: deleted per currency=%s, surveys changed=%d, collections changed=%d",
        dict(deleted), len(changed["survey"]), len(changed["collection"]),
    )
    _republish(changed)


def _republish(changed):
    """Emit the same update events an admin price edit does.

    Uses the live models and publisher, which match the schema as of this
    migration; a fresh database has no rows here, so this never runs there.
    """
    if not (changed["survey"] or changed["collection"]):
        return
    from app.messaging import publish
    from survey_collections.events import CollectionUpdated
    from survey_collections.messaging import serialize_collection
    from survey_collections.models import SurveyCollection
    from surveys.events import SurveyUpdated
    from surveys.messaging import build_survey_payload_or_log
    from surveys.models import Survey

    for survey in Survey.objects.filter(pk__in=changed["survey"]):
        payload = build_survey_payload_or_log(survey, "SurveyUpdated")
        if payload is not None:
            publish(SurveyUpdated(
                aggregate_id=survey.pk, organization_id=payload["organization_id"], survey=payload,
            ))
    for collection in SurveyCollection.objects.filter(pk__in=changed["collection"]):
        payload = serialize_collection(collection)
        if payload["organization_id"]:
            publish(CollectionUpdated(
                aggregate_id=collection.pk, organization_id=payload["organization_id"], collection=payload,
            ))


class Migration(migrations.Migration):

    dependencies = [
        ("pricing", "0004_price_price_exactly_one_parent"),
        ("surveys", "0044_move_unenrolled_surveys_to_ar"),
        ("survey_collections", "0014_surveycollection_cover_id_surveycollection_thumb_id"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
