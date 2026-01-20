from dataclasses import dataclass, fields as dc_fields

from pkg_filters.core import BaseQuerySpec, BaseProjectionSpec
from pkg_filters.core.specs.sort import SortSpec, SortField
from pkg_filters.integrations.django import (
    DjangoPipeline, DjangoQueryContext,
    DjangoRangeFilterHandler,
    DjangoSearchFilterHandler, DjangoSortHandler,
    DjangoAllExactFiltersHandler, DjangoExactFilterHandler,
)

from surveys.inputs import (
    SurveyFilters,
    SurveySortField,
    SurveySortInput,
    QuestionsFilters,
    SurveyCollectionFilters,
    SurveyCollectionSortField,
    SurveyCollectionSortInput,
    UserSurveyFilters,
)


@dataclass(frozen=True)
class SurveyProjection(BaseProjectionSpec):
    pass

SurveySpec = BaseQuerySpec[SurveyFilters, SurveyProjection]



def survey_sort_input_to_spec(inp: SurveySortInput | None) -> SortSpec | None:
    if inp is None:
        return None
    fields = []
    for field in SurveySortField:
        direction = getattr(inp, field.value, None)
        if direction is None:
            continue
        fields.append(SortField(field=field.value, direction=direction.value))
    if not fields:
        return None
    return SortSpec(fields=fields)


SURVEY_SORT_MAP: dict[str, str] = {f.value: f.value for f in SurveySortField}

pipeline = DjangoPipeline([
    DjangoRangeFilterHandler("created_at"),
    DjangoRangeFilterHandler("updated_at"),
    DjangoExactFilterHandler("status", lookup="status__status"),
    DjangoAllExactFiltersHandler(
        excluded={
            "created_at",
            "updated_at",
            "q",
            "status",
            "price_min_cents",
            "price_max_cents",
            "has_discount",
            "is_free",
        }
    ),
    DjangoSearchFilterHandler("q", fields=("title", "description", "short_description")),
    DjangoSortHandler(sort_map=SURVEY_SORT_MAP),
])


@dataclass(frozen=True)
class QuestionProjection(BaseProjectionSpec):
    pass


QuestionSpec = BaseQuerySpec[QuestionsFilters, QuestionProjection]

questions_pipeline = DjangoPipeline([
    DjangoExactFilterHandler("question_type", lookup="type"),
    DjangoAllExactFiltersHandler(excluded={"question_ids", "answered", "question_type"}),
    DjangoSortHandler(sort_map={"order": "order", "section__order": "section__order"}),
])


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


@dataclass(frozen=True)
class UserSurveyProjection(BaseProjectionSpec):
    pass


UserSurveySpec = BaseQuerySpec[UserSurveyFilters, UserSurveyProjection]

user_surveys_pipeline = DjangoPipeline([
    DjangoRangeFilterHandler("submitted_at"),
    DjangoRangeFilterHandler("evaluated_at"),
    DjangoAllExactFiltersHandler(excluded={"submitted_at", "evaluated_at", "submitted"}),
])
