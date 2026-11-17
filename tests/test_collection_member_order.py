"""A collection keeps and saves an order for its members (report #128, story curricula-order 1.1)."""

import importlib
import uuid
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils.timezone import now

import surveys.schemas.schema  # noqa: F401  (resolves the mutation import cycle)
from pkg_auth.authorization import AuthContext, OrgId, UserId

from survey_collections.models import CollectionMembership, SurveyCollection
from survey_collections.schemas.mutations.collections import SurveyCollectionMutations
from survey_collections.types.collection import SurveyCollectionType
from surveys.models import Survey

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_ORG = uuid.UUID("22222222-2222-2222-2222-222222222222")

pytestmark = pytest.mark.django_db

SURVEYS = """
query ($input: SurveysListInput!) {
  surveys(surveysListInput: $input) { items { id } }
}
"""


class _Identity:
    def __init__(self, user):
        self.subject_str = user.id
        self.email_str = user.email
        self.preferred_username = user.username
        self.first_name = ""
        self.last_name = ""


class _Info:
    def __init__(self, user, organization_id=ORG, perms=("collections:update",)):
        class _Context:
            pass

        self.context = _Context()
        self.context.identity = _Identity(user)
        self.context.auth_context = AuthContext(
            user_id=UserId(user.id),
            organization_id=OrgId(organization_id),
            role_names=frozenset({"org-admin"}),
            perms=frozenset(perms),
        )


class _AnonymousContext:
    request = None
    auth_context = None
    currency = None


def _resolver(name):
    for field in SurveyCollectionMutations.__strawberry_definition__.fields:
        if field.name == name:
            return field.base_resolver.wrapped_func
    raise AssertionError(f"resolver not found: {name}")


def _survey():
    return Survey.objects.create(
        organization_id=ORG, status=Survey.STATUS_PUBLISHED, survey_type="curriculum"
    )


def _collection(*members):
    collection = SurveyCollection.objects.create(organization_id=ORG)
    for survey in members:
        collection.append_member(survey)
    return collection


def _members(collection):
    resolver = SurveyCollectionType.__strawberry_definition__.get_field("assessments").base_resolver
    return [s.id for s in resolver.wrapped_func(collection)]


def _listed(collection, sort=None):
    from surveys import schema as schema_module

    query = {"limit": 50, "offset": 0, "filters": {"collectionId": str(collection.id)}}
    if sort is not None:
        query["sort"] = sort
    result = schema_module.schema.execute_sync(
        SURVEYS,
        variable_values={"input": query},
        context_value=_AnonymousContext(),
    )
    assert result.errors is None, result.errors
    return [int(item["id"]) for item in result.data["surveys"]["items"]]


def _reorder(user, collection, ids, **info):
    return _resolver("reorder_collection_surveys")(
        SurveyCollectionMutations(),
        _Info(user, **info),
        collection_id=str(collection.id),
        survey_ids=[str(i) for i in ids],
    )


def _orders(collection):
    return list(
        CollectionMembership.objects.filter(surveycollection=collection)
        .order_by("id")
        .values_list("survey_id", "order")
    )


def test_the_migration_seeds_each_collection_in_link_order():
    a, b, c = _survey(), _survey(), _survey()
    first, second = SurveyCollection.objects.create(organization_id=ORG), SurveyCollection.objects.create(organization_id=ORG)
    # Link order (row id) differs from survey id order, and every order is unset as before the release.
    for collection, survey in [(first, c), (second, b), (first, a), (second, c), (first, b)]:
        CollectionMembership.objects.create(surveycollection=collection, survey=survey, order=0)
    pairs = sorted(CollectionMembership.objects.values_list("surveycollection_id", "survey_id"))

    from django.apps import apps

    importlib.import_module("survey_collections.migrations.0016_collection_member_order").seed_order(apps, None)

    assert sorted(CollectionMembership.objects.values_list("surveycollection_id", "survey_id")) == pairs
    assert _members(first) == [c.id, a.id, b.id]
    assert _members(second) == [b.id, c.id]
    assert _listed(first) == [c.id, a.id, b.id]


def test_a_saved_order_is_returned_by_members_and_listing(user):
    a, b, c = _survey(), _survey(), _survey()
    collection = _collection(a, b, c)

    _reorder(user, collection, [c.id, a.id, b.id])

    assert _members(collection) == [c.id, a.id, b.id]
    assert _listed(collection) == [c.id, a.id, b.id]


@pytest.mark.parametrize("case", ["unknown", "missing", "duplicate"])
def test_a_save_that_does_not_name_each_member_once_is_refused(user, case):
    a, b, c = _survey(), _survey(), _survey()
    outsider = _survey()
    collection = _collection(a, b, c)
    before = _orders(collection)
    ids = {
        "unknown": [a.id, b.id, c.id, outsider.id],
        "missing": [a.id, c.id],
        "duplicate": [a.id, a.id, b.id],
    }[case]

    with pytest.raises(ValidationError):
        _reorder(user, collection, ids)

    assert _orders(collection) == before


def test_another_organization_cannot_reorder(user):
    a, b = _survey(), _survey()
    collection = _collection(a, b)
    before = _orders(collection)

    with pytest.raises(PermissionError):
        _reorder(user, collection, [b.id, a.id], organization_id=OTHER_ORG)

    assert _orders(collection) == before


def test_reordering_needs_the_update_key(user):
    a, b = _survey(), _survey()
    collection = _collection(a, b)

    with pytest.raises(PermissionError):
        _reorder(user, collection, [b.id, a.id], perms=("collections:read",))

    assert _members(collection) == [a.id, b.id]


def test_a_new_member_goes_last(user):
    a, b, c, d = _survey(), _survey(), _survey(), _survey()
    collection = _collection(a, b, c)
    _reorder(user, collection, [c.id, a.id, b.id])

    collection.append_member(d)
    collection.append_member(a)  # already a member: stays where it is

    assert _members(collection) == [c.id, a.id, b.id, d.id]


def test_soft_deleted_members_stay_hidden_and_need_not_be_named(user):
    a, b, gone = _survey(), _survey(), _survey()
    collection = _collection(a, gone, b)
    Survey.objects.filter(pk=gone.pk).update(deleted_at=now())

    _reorder(user, collection, [b.id, a.id])

    assert _members(collection) == [b.id, a.id]
    assert CollectionMembership.objects.get(surveycollection=collection, survey=gone).order == 2


def test_adding_through_the_mutation_puts_the_survey_last(user):
    a, b, c = _survey(), _survey(), _survey()
    collection = _collection(a, b)
    _reorder(user, collection, [b.id, a.id])

    _resolver("add_survey_to_collection")(
        SurveyCollectionMutations(),
        _Info(user, perms=("curriculums:update",)),
        collection_id=str(collection.id),
        survey_id=str(c.id),
    )

    assert _members(collection) == [b.id, a.id, c.id]


def test_an_explicit_sort_still_wins_over_the_saved_order(user):
    a, b, c = _survey(), _survey(), _survey()
    for offset, survey in enumerate([a, b, c]):
        Survey.objects.filter(pk=survey.pk).update(created_at=now() + timedelta(minutes=offset))
    collection = _collection(a, b, c)
    _reorder(user, collection, [b.id, c.id, a.id])

    assert _listed(collection, sort={"createdAt": "DESC"}) == [c.id, b.id, a.id]


def test_a_deleted_collection_cannot_be_reordered(user):
    a, b = _survey(), _survey()
    collection = _collection(a, b)
    SurveyCollection.objects.filter(pk=collection.pk).update(deleted_at=now())

    with pytest.raises(SurveyCollection.DoesNotExist):
        _reorder(user, collection, [b.id, a.id])

    assert _members(collection) == [a.id, b.id]
