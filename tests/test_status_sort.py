"""`status` sorting orders by publication state, not by the column's alphabet.

Ordering on the CharField itself gives archived < draft < pending < published <
suspended, which is why admin listings could not float the actionable rows up.
The rank annotation in `app.status_sort` is what the `status` sort actually
orders by; these tests pin that contract.

They drive the filter pipeline directly rather than POSTing to
``/api/v1/forms/graphql``: the HTTP path needs pkg_auth installed, which this
environment does not have (every test in ``test_queries.py`` fails on it). The
pipeline is the whole of the sorting behaviour — the resolver only annotates the
queryset and hands it over.
"""
from dataclasses import fields as dc_fields

import pytest

from app.status_sort import STATUS_SORT_ORDER, annotate_status_rank
from pkg_filters.integrations.django import DjangoQueryContext
from survey_collections.filters import (
    SurveyCollectionProjection,
    SurveyCollectionSpec,
    collections_pipeline,
    survey_collection_sort_input_to_spec,
)
from survey_collections.inputs import SurveyCollectionFilters, SurveyCollectionSortInput
from survey_collections.models import SurveyCollection
from surveys.filters import (
    SurveyProjection,
    SurveySpec,
    pipeline,
    survey_sort_input_to_spec,
)
from surveys.inputs import SortDirection, SurveyFilters, SurveySortInput
from surveys.models import Survey

pytestmark = pytest.mark.django_db

# Deliberately created in an order alphabetical sorting would not repair.
CREATE_ORDER = ["archived", "draft", "suspended", "published", "pending"]
PUBLISHED_FIRST = list(STATUS_SORT_ORDER)


def _no_filters(cls):
    """These filter dataclasses declare every field required; a listing with no
    filters applied still has to name them all."""
    return cls(**{f.name: None for f in dc_fields(cls)})


def _sorted_survey_statuses(direction):
    qs = annotate_status_rank(Survey.objects.filter(deleted_at__isnull=True))
    spec = SurveySpec(
        limit=50,
        offset=0,
        projection=SurveyProjection(),
        filters=_no_filters(SurveyFilters),
        sort=survey_sort_input_to_spec(SurveySortInput(status=direction)),
    )
    return [s.status for s in pipeline.run(DjangoQueryContext(qs, spec)).stmt]


def test_surveys_status_sort_puts_published_first():
    for status in CREATE_ORDER:
        Survey.objects.create(status=status)

    assert _sorted_survey_statuses(SortDirection.ASC) == PUBLISHED_FIRST


def test_surveys_status_sort_desc_reverses():
    for status in CREATE_ORDER:
        Survey.objects.create(status=status)

    assert _sorted_survey_statuses(SortDirection.DESC) == list(reversed(PUBLISHED_FIRST))


def test_unknown_status_sorts_last_rather_than_raising():
    """A row in a state the vocabulary has not caught up with must not break the query."""
    Survey.objects.create(status="published")
    Survey.objects.create(status="some_new_state")

    assert _sorted_survey_statuses(SortDirection.ASC) == ["published", "some_new_state"]


def test_collections_status_sort_puts_published_first():
    for status in CREATE_ORDER:
        SurveyCollection.objects.create(status=status)

    qs = annotate_status_rank(SurveyCollection.objects.filter(deleted_at__isnull=True))
    spec = SurveyCollectionSpec(
        limit=50,
        offset=0,
        projection=SurveyCollectionProjection(),
        filters=_no_filters(SurveyCollectionFilters),
        sort=survey_collection_sort_input_to_spec(
            SurveyCollectionSortInput(status=SortDirection.ASC)
        ),
    )
    result = collections_pipeline.run(DjangoQueryContext(qs, spec)).stmt
    assert [c.status for c in result] == PUBLISHED_FIRST
