"""Search lists an item once, however many of its translations match (F3).

Report #98, story `forms-listing-filters` 2.1. Search ranks over the
`translations__*` reverse relation, one row per language, so an item whose
`ar` and `en` titles both match was suspected of being listed once per
translation, with `total` counting translations.

Postgres only: sqlite has no full-text search or `pg_trgm`. Run with
`DATABASE_URL` pointing at the local `itq_forms_postgres` container; under the
default sqlite settings every test here is skipped.
"""
import uuid

import pytest
from django.db import connection

from survey_collections.models import SurveyCollection, SurveyCollectionTranslation
from surveys.models import Survey, SurveyTranslation
from taxonomy.models import Category

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(
        connection.vendor != "postgresql", reason="needs Postgres full-text search"
    ),
]

QUERIES = {
    "surveys": """
query ($input: SurveysListInput!) {
  surveys(surveysListInput: $input) {
    total items { id }
    facets { categories { id count } }
  }
}
""",
    "collections": """
query ($input: SurveyCollectionsListInput!) {
  collections(collectionsListInput: $input) {
    total items { id }
    facets { categories { id count } }
  }
}
""",
}


class _AnonymousContext:
    request = None
    auth_context = None
    currency = None


@pytest.fixture(autouse=True)
def _every_tree(settings):
    settings.CATEGORY_TREE_ID = ""


@pytest.fixture(autouse=True)
def _trigram():
    # --no-migrations skips surveys/0032's TrigramExtension.
    with connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def _two_matching_translations(listing, category=None):
    if listing == "surveys":
        obj = Survey.objects.create(
            organization_id=ORG, status=Survey.STATUS_PUBLISHED, category=category
        )
        for language in ("ar", "en"):
            SurveyTranslation.objects.create(survey=obj, language=language, title="Algebra basics")
    else:
        obj = SurveyCollection.objects.create(
            organization_id=ORG, status=SurveyCollection.STATUS_PUBLISHED, category=category
        )
        for language in ("ar", "en"):
            SurveyCollectionTranslation.objects.create(
                collection=obj, language=language, title="Algebra basics"
            )
    return obj


@pytest.mark.parametrize("listing", QUERIES)
def test_an_item_with_two_matching_translations_is_listed_once(listing):
    from surveys import schema as schema_module

    category = Category.objects.create(tree_id=uuid.uuid4(), name="Maths", path_text="maths")
    obj = _two_matching_translations(listing, category)

    result = schema_module.schema.execute_sync(
        QUERIES[listing],
        variable_values={"input": {"limit": 50, "offset": 0, "filters": {"q": "algebra"}}},
        context_value=_AnonymousContext(),
    )

    assert result.errors is None, result.errors
    data = result.data[listing]
    assert [int(item["id"]) for item in data["items"]] == [obj.id]
    assert data["total"] == 1
    assert data["facets"]["categories"] == [{"id": str(category.category_id), "count": 1}]


def _search(listing, filters, sort=None):
    from surveys import schema as schema_module

    variables = {"input": {"limit": 50, "offset": 0, "filters": filters}}
    if sort:
        variables["input"]["sort"] = sort
    result = schema_module.schema.execute_sync(
        QUERIES[listing], variable_values=variables, context_value=_AnonymousContext()
    )
    assert result.errors is None, result.errors
    data = result.data[listing]
    return [int(item["id"]) for item in data["items"]], data["total"]


def _item(listing, *translations):
    """An item with one translation per `(language, title, description)`."""
    if listing == "surveys":
        obj = Survey.objects.create(organization_id=ORG, status=Survey.STATUS_PUBLISHED)
        model, parent = SurveyTranslation, "survey"
    else:
        obj = SurveyCollection.objects.create(
            organization_id=ORG, status=SurveyCollection.STATUS_PUBLISHED
        )
        model, parent = SurveyCollectionTranslation, "collection"
    for language, title, description in translations:
        model.objects.create(
            **{parent: obj},
            language=language,
            title=title,
            description=description,
            slug=f"{language}-{obj.id}",
        )
    return obj


@pytest.mark.parametrize("listing", QUERIES)
def test_items_are_ordered_by_their_best_rank(listing):
    weak = _item(listing, ("ar", "Geometry", "some algebra"), ("en", "Geometry", None))
    strong = _item(listing, ("ar", "Other", None), ("en", "Algebra", "Algebra drills"))

    assert _search(listing, {"q": "algebra"}) == ([strong.id, weak.id], 2)


@pytest.mark.parametrize("listing", QUERIES)
def test_a_trigram_only_match_is_listed_once(listing):
    typo = _item(listing, ("ar", "Algebre", None), ("en", "Algebre", None))
    _item(listing, ("ar", "Geometry", None))

    assert _search(listing, {"q": "algebra"}) == ([typo.id], 1)


def test_a_language_filter_and_q_must_match_the_same_translation():
    _item("collections", ("ar", "Geometry", None), ("en", "Algebra", None))

    assert _search("collections", {"language": "ar", "q": "algebra"}) == ([], 0)


def test_a_language_filter_keeps_an_item_whose_kept_translation_matches():
    obj = _item("collections", ("ar", "Algebra", None), ("en", "Geometry", None))

    assert _search("collections", {"language": "ar", "q": "algebra"}) == ([obj.id], 1)


def test_a_slug_filter_and_q_must_match_the_same_translation():
    obj = _item("surveys", ("ar", "Geometry", None), ("en", "Algebra", None))

    assert _search("surveys", {"slug": f"ar-{obj.id}", "q": "algebra"}) == ([], 0)


@pytest.mark.parametrize("direction", ["ASC", "DESC"])
def test_a_title_sort_under_search_lists_each_collection_once(direction):
    first = _item("collections", ("ar", "Algebra one", None), ("en", "Basic algebra", None))
    second = _item("collections", ("ar", "Algebra two", None), ("en", "Core algebra", None))

    ids, total = _search("collections", {"q": "algebra"}, sort={"title": direction})

    expected = [first.id, second.id]
    assert ids == (expected if direction == "ASC" else expected[::-1])
    assert total == 2
