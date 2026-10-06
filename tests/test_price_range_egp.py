"""The price filter and price facet speak EGP (developer ruling, 2026-10-06).

A visitor types EGP into the listing's price range; prices are stored as
amount_cents. The filter converts the typed bounds, and the facet returns the
bounds the control shows beside the boxes in the same unit. An absent end is
no limit (report #98). Drives the filter pipelines directly, as
test_status_sort.py does.
"""
import uuid
from dataclasses import fields as dc_fields

import pytest
from pkg_filters.core.specs.range import RangeFilterVO
from pkg_filters.integrations.django import DjangoQueryContext

from app.facets import build_price_range_facet
from pricing.models import Price
from survey_collections.filters import (
    SurveyCollectionProjection,
    SurveyCollectionSpec,
    collections_pipeline,
)
from survey_collections.inputs import SurveyCollectionFilters
from survey_collections.models import SurveyCollection
from surveys.filters import SurveyProjection, SurveySpec, pipeline
from surveys.inputs import SurveyFilters
from surveys.models import Survey

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")

pytestmark = pytest.mark.django_db


def _filters(cls, **values):
    return cls(**{f.name: values.get(f.name) for f in dc_fields(cls)})


def _priced(model, cents, parent_field):
    obj = model.objects.create(organization_id=ORG)
    if cents is None:
        Price.objects.filter(**{parent_field: obj}).delete()
    else:
        Price.objects.update_or_create(
            currency="EGP", **{parent_field: obj}, defaults={"amount_cents": cents}
        )
    return obj


@pytest.fixture
def surveys():
    return {
        egp: _priced(Survey, egp * 100, "survey") for egp in (50, 100, 150)
    }


def _survey_ids(price):
    spec = SurveySpec(
        limit=50,
        offset=0,
        projection=SurveyProjection(),
        filters=_filters(SurveyFilters, price=price),
        sort=None,
    )
    return set(pipeline.run(DjangoQueryContext(Survey.objects.all(), spec)).stmt.values_list("id", flat=True))


def _ids(rows, *egp):
    return {rows[e].id for e in egp}


def test_minimum_only_is_egp_with_no_upper_bound(surveys):
    assert _survey_ids(RangeFilterVO(gte=100)) == _ids(surveys, 100, 150)


def test_maximum_only_is_egp_with_no_lower_bound(surveys):
    assert _survey_ids(RangeFilterVO(lte=100)) == _ids(surveys, 50, 100)


def test_both_ends_are_inclusive_egp(surveys):
    assert _survey_ids(RangeFilterVO(gte=50, lte=100)) == _ids(surveys, 50, 100)


def test_exact_price_is_egp(surveys):
    assert _survey_ids(RangeFilterVO(eq=150)) == _ids(surveys, 150)


def test_unpriced_counts_as_free_when_no_lower_bound(surveys):
    unpriced = _priced(Survey, None, "survey")
    assert unpriced.id in _survey_ids(RangeFilterVO(lte=100))
    assert unpriced.id not in _survey_ids(RangeFilterVO(gte=100))


def test_collections_filter_is_egp():
    rows = {egp: _priced(SurveyCollection, egp * 100, "collection") for egp in (50, 150)}
    spec = SurveyCollectionSpec(
        limit=50,
        offset=0,
        projection=SurveyCollectionProjection(),
        filters=_filters(SurveyCollectionFilters, price=RangeFilterVO(gte=100)),
        sort=None,
    )
    qs = collections_pipeline.run(DjangoQueryContext(SurveyCollection.objects.all(), spec)).stmt
    assert set(qs.values_list("id", flat=True)) == {rows[150].id}


def test_facet_bounds_are_egp_covering_every_price():
    _priced(Survey, 5000, "survey")
    _priced(Survey, 15050, "survey")
    facet = build_price_range_facet(Survey.objects.all(), "EGP")
    assert (facet.min, facet.max) == (50, 151)


def test_facet_is_zero_when_nothing_is_priced():
    _priced(Survey, None, "survey")
    facet = build_price_range_facet(Survey.objects.all(), "EGP")
    assert (facet.min, facet.max) == (0, 0)
