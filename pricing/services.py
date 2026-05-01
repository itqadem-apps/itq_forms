"""Service helpers shared by survey/collection mutations to upsert nested prices."""

from __future__ import annotations

from typing import Iterable

import strawberry
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Model

from pricing.inputs import DiscountNestedInput, PriceNestedInput
from pricing.models import Discount, Price

UNSET = strawberry.UNSET


def _set_fields(instance: Model, mapping: dict) -> None:
    for field, value in mapping.items():
        if value is UNSET:
            continue
        setattr(instance, field, value)


def _price_parent_filter(parent: Model) -> dict:
    """Return the FK lookup that scopes a Price to the given parent.

    Accepts either a ``Survey`` or a ``SurveyCollection`` instance. Using the
    model name keeps this helper agnostic of import cycles.
    """
    name = parent.__class__.__name__
    if name == "Survey":
        return {"survey": parent}
    if name == "SurveyCollection":
        return {"collection": parent}
    raise TypeError(f"Unsupported price parent type: {name}")


def _upsert_discount(price: Price, inp: DiscountNestedInput) -> Discount:
    if inp.id is not UNSET and inp.id is not None:
        try:
            discount = Discount.objects.get(pk=inp.id, price=price)
        except Discount.DoesNotExist:
            raise ObjectDoesNotExist(
                f"Discount {inp.id} not found on price {price.pk}"
            )
        _set_fields(discount, {
            "type": inp.type,
            "value": inp.value,
            "starts_at": inp.starts_at,
            "ends_at": inp.ends_at,
            "code": inp.code,
            "max_redemptions": inp.max_redemptions,
        })
        discount.save()
        return discount

    # Create — type/value are required for a brand new discount.
    if inp.type is UNSET or inp.value is UNSET:
        raise ValueError("Discount create requires 'type' and 'value'.")
    return Discount.objects.create(
        price=price,
        type=inp.type,
        value=inp.value,
        starts_at=inp.starts_at if inp.starts_at is not UNSET else None,
        ends_at=inp.ends_at if inp.ends_at is not UNSET else None,
        code=inp.code if inp.code is not UNSET else None,
        max_redemptions=inp.max_redemptions if inp.max_redemptions is not UNSET else None,
    )


def _upsert_price(parent: Model, inp: PriceNestedInput) -> Price:
    parent_filter = _price_parent_filter(parent)

    if inp.id is not UNSET and inp.id is not None:
        try:
            price = Price.objects.get(pk=inp.id, **parent_filter)
        except Price.DoesNotExist:
            raise ObjectDoesNotExist(
                f"Price {inp.id} not found on this {parent.__class__.__name__.lower()}"
            )
        _set_fields(price, {
            "currency": inp.currency,
            "amount_cents": inp.amount_cents,
            "compare_at_amount_cents": inp.compare_at_amount_cents,
        })
        price.save()
    else:
        if inp.currency is UNSET or inp.amount_cents is UNSET:
            raise ValueError("Price create requires 'currency' and 'amount_cents'.")
        price = Price.objects.create(
            currency=inp.currency,
            amount_cents=inp.amount_cents,
            compare_at_amount_cents=inp.compare_at_amount_cents
            if inp.compare_at_amount_cents is not UNSET else None,
            **parent_filter,
        )

    if inp.discounts is not UNSET and inp.discounts:
        for d in inp.discounts:
            _upsert_discount(price, d)

    return price


def upsert_prices_for_parent(
    parent: Model,
    prices: Iterable[PriceNestedInput] | None,
) -> list[Price]:
    """Upsert each ``PriceNestedInput`` (and its nested discounts) under ``parent``.

    Non-destructive: rows not present in the input are left alone. Use the
    dedicated ``delete_price`` / ``delete_discount`` mutations for removal.
    """
    if not prices:
        return []
    return [_upsert_price(parent, p) for p in prices]
