from typing import List, Optional
from datetime import datetime

import strawberry


@strawberry.input
class DiscountNestedInput:
    """Nested under a price in survey/collection mutations.

    ``id`` present → update; absent → create. Caller verifies the row belongs
    to the parent price.
    """

    id: Optional[int] = strawberry.UNSET
    type: Optional[str] = strawberry.UNSET
    value: Optional[int] = strawberry.UNSET
    starts_at: Optional[datetime] = strawberry.UNSET
    ends_at: Optional[datetime] = strawberry.UNSET
    code: Optional[str] = strawberry.UNSET
    max_redemptions: Optional[int] = strawberry.UNSET


@strawberry.input
class PriceNestedInput:
    """Nested under a survey/collection mutation.

    ``id`` present → update; absent → create. Discounts upsert with the same
    rule. Existing prices/discounts not referenced are left untouched (use the
    dedicated ``delete_price`` / ``delete_discount`` mutations to remove).
    """

    id: Optional[int] = strawberry.UNSET
    currency: Optional[str] = strawberry.UNSET
    amount_cents: Optional[int] = strawberry.UNSET
    compare_at_amount_cents: Optional[int] = strawberry.UNSET
    discounts: Optional[List[DiscountNestedInput]] = strawberry.UNSET


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
