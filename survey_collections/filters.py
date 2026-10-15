from dataclasses import dataclass

from django.db.models import OuterRef, QuerySet, Subquery

from pkg_filters.core import BaseQuerySpec, BaseProjectionSpec
from pkg_filters.core.specs.sort import SortSpec, SortField
from pkg_filters.integrations.django import (
    DjangoPipeline,
    DjangoRangeFilterHandler,
    DjangoSortHandler,
    DjangoAllExactFiltersHandler,
    DjangoExactFilterHandler,
)

from app.category_filter import CategorySubtreeFilterHandler
from app.price_filter import DjangoPriceRangeFilterHandler
from app.search import PostgresSearchHandler
from app.status_sort import STATUS_RANK_FIELD
from survey_collections.models import SurveyCollectionTranslation
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


#: The alias the `title` sort orders by (see `alias_title_sort`).
TITLE_SORT_FIELD = "title_sort"


def alias_title_sort(qs: QuerySet) -> QuerySet:
    """Alias each collection's first title, alphabetically, for the `title` sort.

    Ordering by `translations__title` joins one row per translation, so a
    collection with several titles was listed once per title, and under
    search's per-item grouping each title split the item into its own group.
    A scalar subquery keeps one row per collection. An alias costs nothing
    unless the sort uses it.
    """
    return qs.alias(
        **{
            TITLE_SORT_FIELD: Subquery(
                SurveyCollectionTranslation.objects.filter(collection=OuterRef("pk"))
                .order_by("title")
                .values("title")[:1]
            )
        }
    )


SURVEY_COLLECTION_SORT_MAP: dict[str, str] = {
    "created_at": "created_at",
    "updated_at": "updated_at",
    "title": TITLE_SORT_FIELD,
    # Not a column: the rank annotation the resolver adds (`app.status_sort`).
    "status": STATUS_RANK_FIELD,
}

collections_pipeline = DjangoPipeline([
    DjangoRangeFilterHandler("created_at"),
    DjangoRangeFilterHandler("updated_at"),
    DjangoPriceRangeFilterHandler("price"),
    DjangoExactFilterHandler("title", lookup="translations__title"),
    DjangoExactFilterHandler("slug", lookup="translations__slug"),
    DjangoExactFilterHandler("language", lookup="translations__language"),
    CategorySubtreeFilterHandler("category_id"),
    DjangoAllExactFiltersHandler(excluded={"created_at", "updated_at", "q", "title", "slug", "language", "price", "has_discount", "is_free", "currency", "category_id"}),
    PostgresSearchHandler(
        "q",
        fields=("translations__title", "translations__description", "translations__short_description"),
        weights=("A", "B", "C"),
        trigram_field="translations__title",
    ),
    DjangoSortHandler(sort_map=SURVEY_COLLECTION_SORT_MAP),
])
