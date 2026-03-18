from __future__ import annotations

from typing import Optional

import strawberry_django
from strawberry import auto

from pricing.models import Discount


@strawberry_django.type(Discount)
class DiscountType:
    id: auto
    price_id: auto
    type: auto
    value: auto
    starts_at: auto
    ends_at: auto
    code: auto
    max_redemptions: auto
    redemption_count: auto
