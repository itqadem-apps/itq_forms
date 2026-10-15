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

from django.core.exceptions import ValidationError
from django.utils import timezone

from pricing.models import Price
from survey_collections.models import SurveyCollection, SurveyCollectionTranslation
from surveys.models import Survey, SurveyTranslation
from taxonomy.models import Category

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _every_tree(settings):
    """No configured tree: the facet and the filter read every tree, unless a
    test pins one itself."""
    settings.CATEGORY_TREE_ID = ""

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


# Story `forms-listing-filters` 2.1: the filters that run return the right
# items and counts (F2, F4, F5).

FACETS = {
    "surveys": """
query ($input: SurveysListInput!) {
  surveys(surveysListInput: $input) {
    total items { id }
    facets { price { min max } categories { id count children { id count children { id count } } } }
  }
}
""",
    "collections": """
query ($input: SurveyCollectionsListInput!) {
  collections(collectionsListInput: $input) {
    total items { id }
    facets { price { min max } categories { id count children { id count children { id count } } } }
  }
}
""",
}


def _faceted(listing, filters, sort=None):
    from surveys import schema as schema_module

    variables = {"input": {"limit": 50, "offset": 0, "filters": filters}}
    if sort:
        variables["input"]["sort"] = sort
    result = schema_module.schema.execute_sync(
        FACETS[listing], variable_values=variables, context_value=_AnonymousContext()
    )
    assert result.errors is None, result.errors
    data = result.data[listing]
    return {int(item["id"]) for item in data["items"]}, data["facets"]


def _flat_counts(nodes):
    counts = {}
    for node in nodes:
        counts[node["id"]] = node["count"]
        counts.update(_flat_counts(node.get("children") or []))
    return counts


def _price(listing, obj, cents, compare_at=None):
    _, parent_field, _, _ = LISTINGS[listing]
    Price.objects.update_or_create(
        currency="EGP",
        **{parent_field: obj},
        defaults={"amount_cents": cents, "compare_at_amount_cents": compare_at},
    )
    return obj


@pytest.fixture
def tree():
    """`a` → `a.b` → `a.b.c`, an unrelated `x`, and `ab`, whose path only
    shares `a` as a string prefix."""
    tree_id = uuid.uuid4()
    make = lambda path: Category.objects.create(tree_id=tree_id, name=path, path_text=path)
    return {path: make(path) for path in ("a", "a.b", "a.b.c", "x", "ab")}


@pytest.mark.parametrize("listing", LISTINGS)
@pytest.mark.parametrize("selected", ["a", "a.b", "a.b.c"])
def test_a_category_matches_the_items_filed_beneath_it(listing, tree, selected):
    leaf_item = _create(listing, category=tree["a.b.c"])
    _create(listing, category=tree["x"])

    assert _listed(listing, {"categoryId": str(tree[selected].category_id)}) == {leaf_item.id}


@pytest.mark.parametrize("listing", LISTINGS)
def test_a_shared_string_prefix_is_not_ancestry(listing, tree):
    _create(listing, category=tree["ab"])

    assert _listed(listing, {"categoryId": str(tree["a"].category_id)}) == set()


@pytest.mark.parametrize("listing", LISTINGS)
def test_a_category_that_names_no_live_category_matches_nothing(listing, tree):
    _create(listing, category=tree["a"])

    assert _listed(listing, {"categoryId": str(uuid.uuid4())}) == set()


@pytest.mark.parametrize("listing", LISTINGS)
def test_the_category_facet_ignores_its_own_filter_but_not_the_others(listing, tree):
    in_a = _price(listing, _create(listing, category=tree["a"]), 0)
    _price(listing, _create(listing, category=tree["x"]), 0)
    _price(listing, _create(listing, category=tree["x"]), 5000)

    items, facets = _faceted(
        listing, {"categoryId": str(tree["a"].category_id), "isFree": True}
    )

    assert items == {in_a.id}
    counts = _flat_counts(facets["categories"])
    assert counts[str(tree["x"].category_id)] == 1
    assert counts[str(tree["a"].category_id)] == 1


@pytest.mark.parametrize("listing", LISTINGS)
def test_the_price_facet_ignores_its_own_filter_but_not_the_others(listing):
    _price(listing, _create(listing), 1000, compare_at=2000)
    fifty = _price(listing, _create(listing), 5000, compare_at=6000)
    _price(listing, _create(listing), 9000)

    items, facets = _faceted(listing, {"price": {"gte": 40}, "hasDiscount": True})

    assert items == {fifty.id}
    assert facets["price"] == {"min": 10, "max": 50}


@pytest.mark.parametrize("leaf_first", [True, False], ids=["leaf-first", "root-first"])
def test_category_facet_counts_once_per_ancestor_in_any_read_order(leaf_first, monkeypatch):
    from app.facets import build_category_tree_facet

    tree_id = uuid.uuid4()
    paths = ["a", "a.b", "a.b.c"]
    if leaf_first:
        paths.reverse()
    created = {
        path: Category.objects.create(tree_id=tree_id, name=path, path_text=path)
        for path in paths
    }
    # The table's own read order is not insertion order (UUID keys), so pin it.
    live = Category.live.__func__
    order = "-path_text" if leaf_first else "path_text"
    monkeypatch.setattr(
        Category, "live", classmethod(lambda cls, tree_id=None: live(cls, tree_id).order_by(order))
    )
    assert [c.path_text for c in Category.live(tree_id)] == paths
    _create("surveys", category=created["a.b.c"])

    roots = build_category_tree_facet(Survey.objects.all())

    def walk(nodes):
        for node in nodes:
            yield node
            yield from walk(node.children)

    counts = {node.path_text: node.count for node in walk(roots)}
    assert counts == {"a": 1, "a.b": 1, "a.b.c": 1}
    assert [node.path_text for node in roots] == ["a"]


def _translate(listing, obj, language, slug):
    if listing == "surveys":
        SurveyTranslation.objects.create(survey=obj, language=language, title=slug, slug=slug)
    else:
        SurveyCollectionTranslation.objects.create(
            collection=obj, language=language, title=slug, slug=slug
        )


@pytest.mark.parametrize("listing", LISTINGS)
def test_the_category_facet_counts_items_under_a_sort(listing, tree):
    _create(listing, category=tree["x"])
    _create(listing, category=tree["x"])

    _, facets = _faceted(listing, {}, sort={"createdAt": "DESC"})

    assert _flat_counts(facets["categories"])[str(tree["x"].category_id)] == 2


@pytest.mark.parametrize("listing", LISTINGS)
def test_an_item_joined_twice_is_counted_once(listing, tree):
    # One price per item (`price_one_per_*_currency`), so the repeated join is
    # the translations one: both languages carry the slug being filtered on.
    obj = _price(listing, _create(listing, category=tree["x"]), 0)
    _translate(listing, obj, "ar", "same")
    _translate(listing, obj, "en", "same")

    items, facets = _faceted(listing, {"isFree": True, "slug": "same"})

    assert items == {obj.id}
    assert _flat_counts(facets["categories"])[str(tree["x"].category_id)] == 1


@pytest.mark.parametrize("listing", LISTINGS)
def test_a_pipeline_filter_still_narrows_the_category_facet(listing, tree):
    kept = _create(listing, category=tree["x"])
    _translate(listing, kept, "ar", "kept")
    dropped = _create(listing, category=tree["x"])
    _translate(listing, dropped, "ar", "dropped")

    items, facets = _faceted(listing, {"slug": "kept"})

    assert items == {kept.id}
    assert _flat_counts(facets["categories"])[str(tree["x"].category_id)] == 1


@pytest.mark.parametrize("listing", LISTINGS)
@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_category_is_no_filter(listing, tree, blank):
    everything = {_create(listing, category=tree["a"]).id, _create(listing).id}

    assert _listed(listing, {"categoryId": blank}) == everything


@pytest.mark.parametrize("listing", LISTINGS)
def test_a_tombstoned_category_matches_nothing(listing, tree):
    _create(listing, category=tree["a.b.c"])
    Category.objects.filter(pk=tree["a"].pk).update(deleted_at=timezone.now())

    assert _listed(listing, {"categoryId": str(tree["a"].category_id)}) == set()


@pytest.mark.parametrize("listing", LISTINGS)
def test_a_category_outside_the_configured_tree_matches_nothing(listing, tree, settings):
    _create(listing, category=tree["a"])
    settings.CATEGORY_TREE_ID = str(uuid.uuid4())

    assert _listed(listing, {"categoryId": str(tree["a"].category_id)}) == set()


@pytest.mark.parametrize("listing", LISTINGS)
def test_descendants_come_from_the_selected_categorys_own_tree(listing, tree):
    other_tree = uuid.uuid4()
    foreign = Category.objects.create(tree_id=other_tree, name="a.b", path_text="a.b")
    _create(listing, category=foreign)
    own = _create(listing, category=tree["a.b"])

    assert _listed(listing, {"categoryId": str(tree["a"].category_id)}) == {own.id}


def test_an_invalid_configured_tree_raises(tree, settings):
    from app.category_filter import CategorySubtreeFilterHandler

    settings.CATEGORY_TREE_ID = "not-a-uuid"
    handler = CategorySubtreeFilterHandler("category_id")

    with pytest.raises(ValidationError):
        list(handler.apply_to_stmt(Survey.objects.all(), None, str(tree["a"].category_id)))


def test_a_category_whose_parent_is_gone_sits_under_its_nearest_ancestor(tree):
    from app.facets import build_category_tree_facet

    Category.objects.filter(pk=tree["a.b"].pk).update(deleted_at=timezone.now())
    _create("surveys", category=tree["a.b.c"])

    roots = {node.path_text: node for node in build_category_tree_facet(Survey.objects.all())}

    assert "a.b.c" not in roots
    assert [child.path_text for child in roots["a"].children] == ["a.b.c"]
    assert roots["a"].count == 1
    assert roots["a"].children[0].count == 1
