from dataclasses import fields as dc_fields, replace
from typing import List, Optional

import strawberry

from media import embedding
from django.db.models import F, Q
from pkg_filters.integrations.django import DjangoQueryContext
from pkg_filters.integrations.strawberry import has_any_under_prefix, get_root_field_paths
from strawberry.types import Info

from survey_collections.filters import (
    SurveyCollectionProjection,
    SurveyCollectionSpec,
    alias_title_sort,
    collections_pipeline,
    survey_collection_sort_input_to_spec,
)
from survey_collections.inputs import SurveyCollectionFilters, SurveyCollectionFiltersInput, SurveyCollectionsListInput
from survey_collections.types.results import SurveyCollectionsResultsGQL, CollectionsFacetsGQL
from app.facets import build_category_tree_facet, build_price_range_facet
from external_references.query import apply_external_reference_filter, has_external_reference_filter
from survey_collections.models import SurveyCollection
from app.graphql_ids import as_pk
from app.permissions import Permission, holds
from app.platform import scope_listing_to_caller
from app.status_sort import annotate_status_rank
from pricing.currency import SHOP_CURRENCY


def _run_without(qs, spec, **cleared):
    """The pipeline's result with the named filters cleared.

    `qs` is the scoped, hand-filtered set `base_qs` was built from, and the
    pipeline does not paginate, so a facet sees every matching row.
    """
    if spec.filters is not None:
        present = {f.name for f in dc_fields(spec.filters)}
        cleared = {name: value for name, value in cleared.items() if name in present}
        spec = replace(spec, filters=replace(spec.filters, **cleared))
    return collections_pipeline.run(DjangoQueryContext(qs, spec)).stmt


def _collection_staff_q(auth_ctx) -> Q:
    """Unpublished collections go to a holder of ``collections:read`` only."""
    if auth_ctx is None or not holds(auth_ctx, Permission.COLLECTION_READ.value):
        return Q(pk__in=[])
    # Not `Q()`: an empty Q is dropped from an OR, which would leave
    # published-only for staff too.
    return Q(pk__isnull=False)


@strawberry.type
class CollectionsQuery:
    @strawberry.field()
    def collections(self, info: Info, collections_list_input: SurveyCollectionsListInput) -> SurveyCollectionsResultsGQL:
        paths = get_root_field_paths(info, "collections")
        # See the surveys resolver: annotated unconditionally so `status` sorting
        # needs nothing from the pipeline.
        qs = alias_title_sort(
            annotate_status_rank(SurveyCollection.objects.filter(deleted_at__isnull=True))
        )
        auth_ctx = getattr(info.context, "auth_context", None)
        qs = scope_listing_to_caller(qs, auth_ctx, staff_q=_collection_staff_q(auth_ctx))
        filters_input = collections_list_input.filters or SurveyCollectionFiltersInput()

        if filters_input.has_discount is not None:
            if filters_input.has_discount:
                qs = qs.filter(
                    prices__compare_at_amount_cents__isnull=False,
                    prices__compare_at_amount_cents__gt=F("prices__amount_cents"),
                )
            else:
                qs = qs.exclude(
                    prices__compare_at_amount_cents__isnull=False,
                    prices__compare_at_amount_cents__gt=F("prices__amount_cents"),
                )
        if filters_input.currency is not None:
            qs = qs.filter(prices__currency=SHOP_CURRENCY)
        if filters_input.is_free is not None:
            free_filter = Q(prices__amount_cents=0) | Q(prices__isnull=True)
            if filters_input.is_free:
                qs = qs.filter(free_filter)
            else:
                qs = qs.exclude(free_filter)
        ext_ref_active = has_external_reference_filter(filters_input.external_reference)
        if ext_ref_active:
            qs = apply_external_reference_filter(qs, filters_input.external_reference)
        if (
            filters_input.price is not None
            or filters_input.has_discount is not None
            or filters_input.currency is not None
            or filters_input.is_free is not None
            or ext_ref_active
        ):
            qs = qs.distinct()

        filters_data = {}
        for field in dc_fields(SurveyCollectionFilters):
            name = field.name
            if name in {"created_at", "updated_at", "price"}:
                value = getattr(filters_input, name, None)
                filters_data[name] = value.to_vo() if value else None
                continue
            # Integer-pk filters arrive as ``ID`` — strings — and the specs and
            # ORM comparisons downstream expect the integer pk. Switch on the
            # declared type, not the name: ``category_id`` is a UUID
            # (``taxonomy.Category``), so ``int()`` rejected every real one.
            if field.type == Optional[int]:
                filters_data[name] = as_pk(getattr(filters_input, name, None))
                continue
            filters_data[name] = getattr(filters_input, name, None)

        spec = SurveyCollectionSpec(
            limit=collections_list_input.limit,
            offset=collections_list_input.offset,
            projection=SurveyCollectionProjection(),
            filters=SurveyCollectionFilters(**filters_data),
            sort=survey_collection_sort_input_to_spec(collections_list_input.sort),
        )
        base_qs = collections_pipeline.run(DjangoQueryContext(qs, spec)).stmt
        total = base_qs.count()
        items = list(
            base_qs[
                collections_list_input.offset : collections_list_input.offset + collections_list_input.limit
            ]
        )

        embedding.prime_records(info, items, ("items",))

        facets = None
        if has_any_under_prefix(paths, ("facets",)):
            currency = getattr(info.context, "currency", None)
            # Each facet ignores its own filter, so a visitor can still pick
            # another category or widen the price range; every other filter
            # still narrows it.
            categories = build_category_tree_facet(
                _run_without(qs, spec, category_id=None)
            )
            price = build_price_range_facet(_run_without(qs, spec, price=None), currency)
            facets = CollectionsFacetsGQL(categories=categories, price=price)

        return SurveyCollectionsResultsGQL(items=items, total=total, facets=facets)
