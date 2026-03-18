from dataclasses import dataclass

from pkg_filters.core import BaseQuerySpec, BaseProjectionSpec
from pkg_filters.core.specs.sort import SortSpec, SortField
from pkg_filters.integrations.django import (
    DjangoPipeline,
    DjangoRangeFilterHandler,
    DjangoSearchFilterHandler,
    DjangoSortHandler,
    DjangoAllExactFiltersHandler,
)

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


SURVEY_COLLECTION_SORT_MAP: dict[str, str] = {f.value: f.value for f in SurveyCollectionSortField}

collections_pipeline = DjangoPipeline([
    DjangoRangeFilterHandler("created_at"),
    DjangoRangeFilterHandler("updated_at"),
    DjangoAllExactFiltersHandler(excluded={"created_at", "updated_at", "q"}),
    DjangoSearchFilterHandler("q", fields=("title", "description", "short_description")),
    DjangoSortHandler(sort_map=SURVEY_COLLECTION_SORT_MAP),
])
