from dataclasses import dataclass, fields as dc_fields

from pkg_filters.core import BaseQuerySpec, BaseProjectionSpec
from pkg_filters.core.specs.sort import SortSpec, SortField
from pkg_filters.integrations.django import (
    DjangoPipeline, DjangoQueryContext,
    DjangoRangeFilterHandler,
    DjangoSortHandler,
    DjangoAllExactFiltersHandler, DjangoExactFilterHandler,
)

from app.search import PostgresSearchHandler
from surveys.inputs import (
    SurveyFilters,
    SurveySortField,
    SurveySortInput,
    QuestionsFilters,
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
    DjangoExactFilterHandler("status"),
    DjangoExactFilterHandler("slug", lookup="translations__slug"),
    DjangoAllExactFiltersHandler(
        excluded={
            "created_at",
            "updated_at",
            "q",
            "status",
            "slug",
            "price_min_cents",
            "price_max_cents",
            "has_discount",
            "is_free",
            "currency",
        }
    ),
    PostgresSearchHandler(
        "q",
        fields=("translations__title", "translations__description", "translations__short_description"),
        weights=("A", "B", "C"),
        trigram_field="translations__title",
    ),
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
