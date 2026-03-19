from dataclasses import dataclass

from pkg_filters.core import BaseQuerySpec, BaseProjectionSpec
from pkg_filters.core.specs.sort import SortSpec, SortField
from pkg_filters.integrations.django import (
    DjangoPipeline,
    DjangoRangeFilterHandler,
    DjangoSortHandler,
    DjangoAllExactFiltersHandler,
    DjangoExactFilterHandler,
)

from app.search import PostgresSearchHandler
from survey_collections.inputs import (
    SurveyCollectionFilters,
    SurveyCollectionSortField,
    SurveyCollectionSortInput,
)


@dataclass(frozen=True)
class SurveyCollectionProjection(BaseProjectionSpec):
    pass


SurveyCollectionSpec = BaseQuerySpec[SurveyCollectionFilters, SurveyCollectionProjection]


def survey_collection_sort_input_to_spec(inp: SurveyCollectionSortInput | None) -> SortSpec | None:
    if inp is None:
        return None
    fields = []
    for field in SurveyCollectionSortField:
        direction = getattr(inp, field.value, None)
        if direction is None:
            continue
        fields.append(SortField(field=field.value, direction=direction.value))
    if not fields:
        return None
    return SortSpec(fields=fields)


SURVEY_COLLECTION_SORT_MAP: dict[str, str] = {
    "created_at": "created_at",
    "updated_at": "updated_at",
    "title": "translations__title",
}

collections_pipeline = DjangoPipeline([
    DjangoRangeFilterHandler("created_at"),
    DjangoRangeFilterHandler("updated_at"),
    DjangoExactFilterHandler("title", lookup="translations__title"),
    DjangoExactFilterHandler("slug", lookup="translations__slug"),
    DjangoExactFilterHandler("language", lookup="translations__language"),
    DjangoAllExactFiltersHandler(excluded={"created_at", "updated_at", "q", "title", "slug", "language"}),
    PostgresSearchHandler(
        "q",
        fields=("translations__title", "translations__description", "translations__short_description"),
        weights=("A", "B", "C"),
        trigram_field="translations__title",
    ),
    DjangoSortHandler(sort_map=SURVEY_COLLECTION_SORT_MAP),
])
