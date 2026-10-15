"""The listing filters a visitor sends reach the query instead of failing it.

Report #98, story `forms-listing-filters` 1.1. A `categoryId` is a UUID, and the
resolvers used to coerce every `*_id` filter through `as_pk`, so each one failed
with "Invalid id" (F1). `price` was an Int range, so a typed `12.5` failed
validation (F6). Both hid behind an empty listing on the frontend.

These go through `schema.execute_sync`, because both faults lived in the
resolver and the schema, which the pipeline-level price tests never reach.
"""
import uuid

import pytest

from pricing.models import Price
from survey_collections.models import SurveyCollection
from surveys.models import Survey
from taxonomy.models import Category

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")

pytestmark = pytest.mark.django_db

SURVEYS = """
query ($input: SurveysListInput!) {
  surveys(surveysListInput: $input) { total items { id } }
}
"""

COLLECTIONS = """
query ($input: SurveyCollectionsListInput!) {
  collections(collectionsListInput: $input) { total items { id } }
}
"""

LISTINGS = {
    "surveys": (Survey, "survey", SURVEYS, Survey.STATUS_PUBLISHED),
    "collections": (SurveyCollection, "collection", COLLECTIONS, SurveyCollection.STATUS_PUBLISHED),
}


class _AnonymousContext:
    """A signed-out visitor: the public catalog of published rows."""

    request = None
    auth_context = None
    currency = None


def _execute(query, filters):
    from surveys import schema as schema_module

    return schema_module.schema.execute_sync(
        query,
        variable_values={"input": {"limit": 50, "offset": 0, "filters": filters}},
        context_value=_AnonymousContext(),
    )


def _listed(listing, filters):
    _, _, query, _ = LISTINGS[listing]
    result = _execute(query, filters)
    assert result.errors is None, result.errors
    return {int(item["id"]) for item in result.data[listing]["items"]}


def _create(listing, **fields):
    model, _, _, published = LISTINGS[listing]
    return model.objects.create(organization_id=ORG, status=published, **fields)


def _priced(listing, cents):
    _, parent_field, _, _ = LISTINGS[listing]
    obj = _create(listing)
    Price.objects.update_or_create(
        currency="EGP", **{parent_field: obj}, defaults={"amount_cents": cents}
    )
    return obj


@pytest.fixture
def categories():
    tree = uuid.uuid4()
    return (
        Category.objects.create(tree_id=tree, name="C", path_text="C"),
        Category.objects.create(tree_id=tree, name="Other", path_text="Other"),
    )


@pytest.mark.parametrize("listing", LISTINGS)
def test_category_filter_takes_the_uuid_a_category_has(listing, categories):
    wanted, other = categories
    inside = _create(listing, category=wanted)
    _create(listing, category=other)

    assert _listed(listing, {"categoryId": str(wanted.category_id)}) == {inside.id}


@pytest.mark.parametrize("listing", LISTINGS)
def test_decimal_lower_bound_validates_and_compares_in_cents(listing):
    _priced(listing, 1200)
    above = _priced(listing, 1300)

    assert _listed(listing, {"price": {"gte": 12.5}}) == {above.id}


@pytest.mark.parametrize("listing", LISTINGS)
def test_a_one_ended_bound_has_no_lower_limit_and_unpriced_counts_as_free(listing):
    cheap = _priced(listing, 5000)
    _priced(listing, 15000)
    unpriced = _create(listing)
    _, parent_field, _, _ = LISTINGS[listing]
    Price.objects.filter(**{parent_field: unpriced}).delete()

    assert _listed(listing, {"price": {"lte": 100}}) == {cheap.id, unpriced.id}


@pytest.mark.parametrize(
    "listing, field",
    [("surveys", "id"), ("surveys", "collectionId"), ("collections", "id")],
)
def test_integer_id_filters_still_reject_a_non_integer(listing, field):
    _, _, query, _ = LISTINGS[listing]
    result = _execute(query, {field: "x"})

    assert result.errors, result.data
    assert "Invalid id" in result.errors[0].message


def test_an_integer_id_filter_still_matches_by_pk():
    wanted = _create("surveys")
    _create("surveys")

    assert _listed("surveys", {"id": str(wanted.id)}) == {wanted.id}
