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
)


@dataclass(frozen=True)
class SurveyProjection(BaseProjectionSpec):
    pass

SurveySpec = BaseQuerySpec[SurveyFilters, SurveyProjection]



def survey_sort_input_to_spec(inp: SurveySortInput | None) -> SortSpec | None:
    if inp is None or not inp.fields:
        return None
    return SortSpec(
        fields=[
            SortField(
                field=f.field.value,
                direction=f.direction.value,
            )
            for f in inp.fields
        ]
    )


SURVEY_SORT_MAP: dict[str, str] = {f.value: f.value for f in SurveySortField}
SURVEY_SORT_MAP["status"] = "status__status"

pipeline = DjangoPipeline([
    DjangoRangeFilterHandler("created_at"),
    DjangoRangeFilterHandler("updated_at"),
    DjangoExactFilterHandler("status", lookup="status__status"),
    DjangoAllExactFiltersHandler(excluded={"created_at", "updated_at", "q", "status"}),
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
