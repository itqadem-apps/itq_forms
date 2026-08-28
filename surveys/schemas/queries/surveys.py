from dataclasses import fields as dc_fields
from typing import List

import strawberry
from strawberry.types import Info
from django.db.models import F, Q
from pkg_filters.integrations.django import DjangoQueryContext
from pkg_filters.integrations.strawberry import has_any_under_prefix, get_root_field_paths

from external_references.query import apply_external_reference_filter, has_external_reference_filter
from surveys.filters import SurveyProjection, SurveySpec, pipeline, survey_sort_input_to_spec
from surveys.inputs import SurveyFilters, SurveyFiltersInput, SurveysListInput
from surveys.models import Survey
from app.facets import build_category_tree_facet, build_price_range_facet
from surveys.types.results import SurveyResultsGQL, SurveysFacetsGQL


@strawberry.type
class SurveysQuery:
    @strawberry.field()
    def surveys(self, info: Info, surveys_list_input: SurveysListInput) -> SurveyResultsGQL:
        paths = get_root_field_paths(info, "surveys")
        qs = Survey.objects.filter(deleted_at__isnull=True)
        if has_any_under_prefix(paths, ("items", "contentType")):
            qs = qs.select_related("content_type")

        filters_input: SurveyFiltersInput | None = surveys_list_input.filters
        if filters_input:
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
        for field in dc_fields(SurveyFilters):
            name = field.name
            if name in {"created_at", "updated_at", "price"}:
                value = getattr(filters_input, name, None) if filters_input else None
                filters_data[name] = value.to_vo() if value else None
                continue
            filters_data[name] = getattr(filters_input, name, None) if filters_input else None

        spec = SurveySpec(
            limit=surveys_list_input.limit,
            offset=surveys_list_input.offset,
            projection=SurveyProjection(),
            filters=SurveyFilters(**filters_data),
            sort=survey_sort_input_to_spec(surveys_list_input.sort),
        )
        base_qs = pipeline.run(DjangoQueryContext(qs, spec)).stmt

        total = base_qs.count()
        items = base_qs[surveys_list_input.offset : surveys_list_input.offset + surveys_list_input.limit]

        facets = None
        if has_any_under_prefix(paths, ("facets",)):
            currency = getattr(info.context, "currency", None)
            categories = build_category_tree_facet(base_qs)
            price = build_price_range_facet(base_qs, currency)
            facets = SurveysFacetsGQL(categories=categories, price=price)

        return SurveyResultsGQL(items=items, total=total, facets=facets)
