from dataclasses import dataclass

from pkg_filters.core import BaseQuerySpec, BaseProjectionSpec
from pkg_filters.core.specs.sort import SortSpec, SortField
from pkg_filters.integrations.django import (
    DjangoPipeline,
    DjangoRangeFilterHandler,
    DjangoSortHandler,
    DjangoExactFilterHandler,
    DjangoAllExactFiltersHandler,
)

from .inputs import UserSurveyFilters, UserSurveySortField, UserSurveySortInput


@dataclass(frozen=True)
class UserSurveyProjection(BaseProjectionSpec):
    pass


UserSurveySpec = BaseQuerySpec[UserSurveyFilters, UserSurveyProjection]


def user_survey_sort_input_to_spec(inp: UserSurveySortInput | None) -> SortSpec | None:
    if inp is None:
        return None
    fields = []
    for field in UserSurveySortField:
        direction = getattr(inp, field.value, None)
        if direction is None:
            continue
        fields.append(SortField(field=field.value, direction=direction.value))
    if not fields:
        return None
    return SortSpec(fields=fields)


USER_SURVEY_SORT_MAP: dict[str, str] = {f.value: f.value for f in UserSurveySortField}

user_surveys_pipeline = DjangoPipeline([
    DjangoRangeFilterHandler("submitted_at"),
    DjangoRangeFilterHandler("evaluated_at"),
    DjangoExactFilterHandler("survey_type", lookup="survey__survey_type"),
    DjangoExactFilterHandler("collection_id", lookup="survey__collections__id"),
    DjangoExactFilterHandler("collection_type", lookup="survey__collections__type"),
    DjangoAllExactFiltersHandler(excluded={"submitted_at", "evaluated_at", "submitted", "survey_type", "collection_id", "collection_type"}),
    DjangoSortHandler(sort_map=USER_SURVEY_SORT_MAP),
])
