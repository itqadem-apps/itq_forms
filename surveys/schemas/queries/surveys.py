from dataclasses import fields as dc_fields
from typing import List

import strawberry
from django.db.models import Count, F, Q
from pkg_filters.integrations.django import DjangoQueryContext
from pkg_filters.integrations.strawberry import has_any_under_prefix, get_root_field_paths

from surveys.filters import SurveyProjection, SurveySpec, pipeline, survey_sort_input_to_spec
from surveys.inputs import SurveyFilters, SurveyFiltersInput, SurveysListInput
from surveys.models import Survey
from surveys.types import FacetGQL, FacetValueGQL, SurveyResultsGQL


@strawberry.type
class SurveysQuery:
    @strawberry.field()
    def surveys(self, info, surveys_list_input: SurveysListInput) -> SurveyResultsGQL:
        paths = get_root_field_paths(info, "surveys")
        qs = Survey.objects.all()
        if has_any_under_prefix(paths, ("items", "contentType")):
            qs = qs.select_related("content_type")

        filters_input: SurveyFiltersInput | None = surveys_list_input.filters
        if filters_input:
            if filters_input.price_min_cents is not None:
                qs = qs.filter(prices__amount_cents__gte=filters_input.price_min_cents)
            if filters_input.price_max_cents is not None:
                qs = qs.filter(prices__amount_cents__lte=filters_input.price_max_cents)
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
            if filters_input.is_free is not None:
                free_filter = Q(prices__amount_cents=0) | Q(prices__isnull=True)
                if filters_input.is_free:
                    qs = qs.filter(free_filter)
                else:
                    qs = qs.exclude(free_filter)
            if (
                filters_input.price_min_cents is not None
                or filters_input.price_max_cents is not None
                or filters_input.has_discount is not None
                or filters_input.is_free is not None
            ):
                qs = qs.distinct()
        filters_data = {}
        for field in dc_fields(SurveyFilters):
            name = field.name
            if name in {"created_at", "updated_at"}:
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

        facets: List[FacetGQL] = []
        if has_any_under_prefix(paths, ("facets",)):
            status_values = [
                FacetValueGQL(value=row["status__status"], count=row["count"])
                for row in base_qs.values("status__status")
                .annotate(count=Count("id"))
                .order_by("status__status")
            ]
            facets.append(FacetGQL(name="status", values=status_values))

            survey_type_values = [
                FacetValueGQL(value=row["survey_type"], count=row["count"])
                for row in base_qs.values("survey_type")
                .annotate(count=Count("id"))
                .order_by("survey_type")
            ]
            facets.append(FacetGQL(name="survey_type", values=survey_type_values))

            language_values = [
                FacetValueGQL(value=row["language"], count=row["count"])
                for row in base_qs.values("language").annotate(count=Count("id")).order_by("language")
            ]
            facets.append(FacetGQL(name="language", values=language_values))

        return SurveyResultsGQL(items=items, total=total, facets=facets)
