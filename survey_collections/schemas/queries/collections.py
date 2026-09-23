from dataclasses import fields as dc_fields
from typing import List

import strawberry
from django.db.models import F, Q
from pkg_filters.integrations.django import DjangoQueryContext
from pkg_filters.integrations.strawberry import has_any_under_prefix, get_root_field_paths
from strawberry.types import Info

from survey_collections.filters import (
    SurveyCollectionProjection,
    SurveyCollectionSpec,
    collections_pipeline,
    survey_collection_sort_input_to_spec,
)
from survey_collections.inputs import SurveyCollectionFilters, SurveyCollectionFiltersInput, SurveyCollectionsListInput
from survey_collections.types.results import SurveyCollectionsResultsGQL, CollectionsFacetsGQL
from app.facets import build_category_tree_facet, build_price_range_facet
from external_references.query import apply_external_reference_filter, has_external_reference_filter
from survey_collections.models import SurveyCollection
from app.graphql_ids import as_pk
from app.platform import is_platform_context
from app.status_sort import annotate_status_rank


def _scope_to_caller(qs, auth_ctx):
    """Keep another organization's unpublished collections out of the listing.

    SPEC-forms-permission-gates CAP-3, collections only. The row-scope gate
    (CAP-2) closed single-row access; this closes the listing, which was
    returning every organization's rows to every caller.

    The scope is a union, not plain org ownership, because this resolver serves
    two callers at once: `AdminCollections` (the admin listing) and
    `Collections` (the public catalog page at
    `/educational-resources/[type]`), and the forms GraphQL proxy forwards
    `x-organization-id` on *every* operation
    (`frontend/lyr-surveys/server/api/forms/graphql.post.ts:17`). Scoping to
    plain ownership would therefore empty the catalog for any signed-in
    shopper. A published collection is already public — anonymous callers see
    it today — so including other organizations' published rows discloses
    nothing new, while drafts and the rest stay with their owner.

    Anonymous callers are left exactly as they were. Whether this listing
    should be a published-only public catalog is the open question CAP-3 is
    blocked on, and narrowing the anonymous path here would settle it by
    accident.
    """
    if auth_ctx is None or is_platform_context(auth_ctx):
        return qs
    return qs.filter(
        Q(organization_id=auth_ctx.organization_id.value)
        | Q(status=SurveyCollection.STATUS_PUBLISHED)
    )


@strawberry.type
class CollectionsQuery:
    @strawberry.field()
    def collections(self, info: Info, collections_list_input: SurveyCollectionsListInput) -> SurveyCollectionsResultsGQL:
        paths = get_root_field_paths(info, "collections")
        # See the surveys resolver: annotated unconditionally so `status` sorting
        # needs nothing from the pipeline.
        qs = annotate_status_rank(SurveyCollection.objects.filter(deleted_at__isnull=True))
        qs = _scope_to_caller(qs, getattr(info.context, "auth_context", None))
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
            qs = qs.filter(prices__currency=filters_input.currency)
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
            # Id filters arrive as ``ID`` — strings. The specs and the ORM
            # comparisons downstream expect the integer pk.
            if name == "id" or name.endswith("_id"):
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

        facets = None
        if has_any_under_prefix(paths, ("facets",)):
            currency = getattr(info.context, "currency", None)
            categories = build_category_tree_facet(base_qs)
            price = build_price_range_facet(base_qs, currency)
            facets = CollectionsFacetsGQL(categories=categories, price=price)

        return SurveyCollectionsResultsGQL(items=items, total=total, facets=facets)
