from typing import Optional
from datetime import datetime

import strawberry


@strawberry.input
class PriceInput:
    currency: str
    amount_cents: int
    compare_at_amount_cents: Optional[int] = strawberry.UNSET
    survey_id: Optional[int] = strawberry.UNSET
    collection_id: Optional[int] = strawberry.UNSET


@strawberry.input
class PriceUpdateInput:
    currency: Optional[str] = strawberry.UNSET
    amount_cents: Optional[int] = strawberry.UNSET
    compare_at_amount_cents: Optional[int] = strawberry.UNSET


@strawberry.input
class DiscountInput:
    price_id: int
    type: str
    value: int
    starts_at: Optional[datetime] = strawberry.UNSET
    ends_at: Optional[datetime] = strawberry.UNSET
    code: Optional[str] = strawberry.UNSET
    max_redemptions: Optional[int] = strawberry.UNSET


@strawberry.input
class DiscountUpdateInput:
    type: Optional[str] = strawberry.UNSET
    value: Optional[int] = strawberry.UNSET
    starts_at: Optional[datetime] = strawberry.UNSET
    ends_at: Optional[datetime] = strawberry.UNSET
    code: Optional[str] = strawberry.UNSET
    max_redemptions: Optional[int] = strawberry.UNSET
