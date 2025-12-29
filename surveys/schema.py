from dataclasses import fields as dc_fields
from typing import List

import strawberry
import strawberry_django
from django.db.models import Count
from pkg_filters.integrations.django import DjangoQueryContext
from pkg_filters.integrations.strawberry import has_any_under_prefix, get_root_field_paths
from strawberry_django.optimizer import DjangoOptimizerExtension

from app.auth import strawberry_auth
from .filters import pipeline, survey_sort_input_to_spec, SurveyProjection, SurveySpec
from .inputs import SurveyFilters, SurveyFiltersInput, SurveysListInput
from .models import Survey
from .types import FacetGQL, FacetValueGQL, SurveyResultsGQL, SurveyType
from strawberry.types import Info

RequireAuth = strawberry_auth.require_authenticated()


@strawberry.type
class Query:
    @strawberry.field()
    def surveys(
            self,
            info,
            surveys_list_input: SurveysListInput,
    ) -> SurveyResultsGQL:
        paths = get_root_field_paths(info, "surveys")
        qs = Survey.objects.all()
        if has_any_under_prefix(paths, ("items", "contentType")):
            qs = qs.select_related("content_type")

        filters_input: SurveyFiltersInput | None = surveys_list_input.filters
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
        items = base_qs[surveys_list_input.offset: surveys_list_input.offset + surveys_list_input.limit]

        facets: List[FacetGQL] = []
        if has_any_under_prefix(paths, ("facets",)):
            status_values = [
                FacetValueGQL(value=row["status__status"], count=row["count"])
                for row in base_qs.values("status__status")
                .annotate(count=Count("id"))
                .order_by("status__status")
            ]
            facets.append(FacetGQL(name="status", values=status_values))

            assessment_type_values = [
                FacetValueGQL(value=row["assessment_type"], count=row["count"])
                for row in base_qs.values("assessment_type")
                .annotate(count=Count("id"))
                .order_by("assessment_type")
            ]
            facets.append(FacetGQL(name="assessment_type", values=assessment_type_values))

            language_values = [
                FacetValueGQL(value=row["language"], count=row["count"])
                for row in base_qs.values("language").annotate(count=Count("id")).order_by("language")
            ]
            facets.append(FacetGQL(name="language", values=language_values))

        return SurveyResultsGQL(items=items, total=total, facets=facets)


    @strawberry.field(permission_classes=[RequireAuth])
    def me(self, info: Info) -> str:
        return info.context.user.identity.preferred_username



schema = strawberry.Schema(
    query=Query,
    extensions=[
        DjangoOptimizerExtension,
    ],
)
