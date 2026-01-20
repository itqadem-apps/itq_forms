from dataclasses import fields as dc_fields
from typing import List

import strawberry
from django.db.models import Count
from pkg_filters.integrations.django import DjangoQueryContext
from pkg_filters.integrations.strawberry import has_any_under_prefix, get_root_field_paths

from surveys.filters import (
    SurveyCollectionProjection,
    SurveyCollectionSpec,
    collections_pipeline,
    survey_collection_sort_input_to_spec,
)
from surveys.inputs import SurveyCollectionFilters, SurveyCollectionFiltersInput, SurveyCollectionsListInput
from surveys.types import FacetGQL, FacetValueGQL, SurveyCollectionsResultsGQL
from survey_collections.models import SurveyCollection
from strawberry.types import Info


@strawberry.type
class CollectionsQuery:
    @strawberry.field()
    def collections(self, info: Info, collections_list_input: SurveyCollectionsListInput) -> SurveyCollectionsResultsGQL:
        paths = get_root_field_paths(info, "collections")
        qs = SurveyCollection.objects.all()
        filters_input = collections_list_input.filters or SurveyCollectionFiltersInput()
        filters_data = {}
        for field in dc_fields(SurveyCollectionFilters):
            name = field.name
            if name in {"created_at", "updated_at"}:
                value = getattr(filters_input, name, None)
                filters_data[name] = value.to_vo() if value else None
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
        facets: List[FacetGQL] = []
        if has_any_under_prefix(paths, ("facets",)):
            status_values = [
                FacetValueGQL(value=row["status"], count=row["count"])
                for row in base_qs.values("status").annotate(count=Count("id")).order_by("status")
            ]
            facets.append(FacetGQL(name="status", values=status_values))

            privacy_values = [
                FacetValueGQL(value=row["privacy_status"], count=row["count"])
                for row in base_qs.values("privacy_status")
                .annotate(count=Count("id"))
                .order_by("privacy_status")
            ]
            facets.append(FacetGQL(name="privacy_status", values=privacy_values))

            language_values = [
                FacetValueGQL(value=row["language"], count=row["count"])
                for row in base_qs.values("language").annotate(count=Count("id")).order_by("language")
            ]
            facets.append(FacetGQL(name="language", values=language_values))

            type_values = [
                FacetValueGQL(value=row["type"], count=row["count"])
                for row in base_qs.values("type").annotate(count=Count("id")).order_by("type")
            ]
            facets.append(FacetGQL(name="type", values=type_values))

        return SurveyCollectionsResultsGQL(items=items, total=total, facets=facets)
