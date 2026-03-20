"""
Custom price range filter handler that treats items with no prices as free (0).

When gte is 0 (or not set), items without any prices are included in the results.
"""
from __future__ import annotations

from typing import Any

from django.db.models import Q, QuerySet

from pkg_filters.core import BaseRangeFilterHandler
from pkg_filters.core.specs.range import RangeFilterVO
from pkg_filters.integrations.django import DjangoQueryContext


class DjangoPriceRangeFilterHandler(BaseRangeFilterHandler):
    """
    Range filter on prices__amount_cents that includes items with no prices
    when the lower bound is 0 or absent.

    Usage in a pipeline:
        DjangoPriceRangeFilterHandler("price")
    """

    def __init__(self, filter_attr: str = "price", *, field: str = "prices__amount_cents") -> None:
        super().__init__(filter_attr)
        self._field = field

    def apply_to_stmt(self, stmt: QuerySet, ctx: Any, rf: RangeFilterVO) -> QuerySet:
        no_prices = Q(prices__isnull=True)
        price_q = Q()

        if rf.eq is not None:
            if rf.eq == 0:
                price_q = Q(**{self._field: 0}) | no_prices
            else:
                price_q = Q(**{self._field: rf.eq})
        else:
            has_lower = False

            if rf.gt is not None:
                price_q &= Q(**{f"{self._field}__gt": rf.gt})
                has_lower = True
            if rf.gte is not None:
                price_q &= Q(**{f"{self._field}__gte": rf.gte})
                if rf.gte > 0:
                    has_lower = True

            if rf.lt is not None:
                price_q &= Q(**{f"{self._field}__lt": rf.lt})
            if rf.lte is not None:
                price_q &= Q(**{f"{self._field}__lte": rf.lte})

            # Include items with no prices when lower bound is 0 or absent
            if not has_lower:
                price_q = price_q | no_prices

        return stmt.filter(price_q).distinct()
