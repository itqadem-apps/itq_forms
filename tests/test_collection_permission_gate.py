"""Collection writes require a collections:* key.

`create`/`update`/`delete_survey_collection` carried `RequireAuth` and nothing
else: the `collections:*` keys existed in the `Permission` enum but were never
checked on any resolver, so any authenticated caller could create, edit or
delete a collection. The survey mutations had been gated by `check_permission`
all along; these are brought onto the same footing.

Platform-org callers bypass the key check, as they do everywhere else.
"""
import os
import uuid

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
django.setup()

import surveys.schemas.schema  # noqa: F401  (resolves the mutation import cycle)
from pkg_auth.authorization import AuthContext, OrgId, UserId

import app.platform as platform
from survey_collections.inputs import SurveyCollectionInput
from survey_collections.models import SurveyCollection
from survey_collections.schemas.mutations.collections import SurveyCollectionMutations

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")
PLATFORM_ORG = uuid.UUID("33333333-3333-3333-3333-333333333333")

ALL_KEYS = frozenset(
    f"collections:{action}" for action in ("create", "read", "update", "delete")
)
#: Every survey key and no collection key — proves the gate reads the
#: collection axis rather than falling through to the assessment one.
SURVEY_KEYS_ONLY = frozenset(
    f"surveys:{action}" for action in ("create", "read", "update", "delete")
)


class _Identity:
    def __init__(self, user):
        self.subject_str = user.id
        self.email_str = user.email
        self.preferred_username = user.username
        self.first_name = ""
        self.last_name = ""


class _Context:
    def __init__(self, user, perms, organization_id=ORG):
        self.identity = _Identity(user)
        self.auth_context = AuthContext(
            user_id=UserId(user.id),
            organization_id=OrgId(organization_id),
            role_names=frozenset({"org-admin"}),
            perms=perms,
        )


class _Info:
    def __init__(self, user, perms, organization_id=ORG):
        self.context = _Context(user, perms, organization_id)


@pytest.fixture(autouse=True)
def platform_org():
    previous = (platform._platform_org_id, platform._resolved)
    platform._platform_org_id = OrgId(PLATFORM_ORG)
    platform._resolved = True
    yield
    platform._platform_org_id, platform._resolved = previous


@pytest.fixture
def collection(db):
    return SurveyCollection.objects.create(organization_id=ORG)


def _resolver(name):
    for field in SurveyCollectionMutations.__strawberry_definition__.fields:
        if field.name == name:
            return field.base_resolver.wrapped_func
    raise AssertionError(f"resolver not found: {name}")


def _create(user, perms, organization_id=ORG):
    return _resolver("create_survey_collection")(
        SurveyCollectionMutations(),
        _Info(user, perms, organization_id),
        input=SurveyCollectionInput(),
    )


def _update(user, perms, collection, organization_id=ORG):
    return _resolver("update_survey_collection")(
        SurveyCollectionMutations(),
        _Info(user, perms, organization_id),
        id=str(collection.pk),
        input=SurveyCollectionInput(),
    )


def _delete(user, perms, collection, organization_id=ORG):
    return _resolver("delete_survey_collection")(
        SurveyCollectionMutations(),
        _Info(user, perms, organization_id),
        id=str(collection.pk),
    )


# --- a caller without the key is refused -----------------------------------

def test_create_without_the_key_is_refused(user, db):
    with pytest.raises(PermissionError):
        _create(user, SURVEY_KEYS_ONLY)

    assert not SurveyCollection.objects.exists()


def test_update_without_the_key_is_refused(user, collection):
    with pytest.raises(PermissionError):
        _update(user, SURVEY_KEYS_ONLY, collection)


def test_delete_without_the_key_is_refused(user, collection):
    with pytest.raises(PermissionError):
        _delete(user, SURVEY_KEYS_ONLY, collection)

    collection.refresh_from_db()
    assert collection.deleted_at is None


# --- a caller holding the key still gets through ---------------------------

def test_create_with_the_key_succeeds(user, db):
    assert _create(user, ALL_KEYS).pk is not None


def test_update_with_the_key_succeeds(user, collection):
    assert _update(user, ALL_KEYS, collection).pk == collection.pk


def test_delete_with_the_key_succeeds(user, collection):
    assert _delete(user, ALL_KEYS, collection).success is True

    collection.refresh_from_db()
    assert collection.deleted_at is not None


# --- the platform org bypasses the key check -------------------------------

def test_platform_creates_without_holding_any_collection_key(user, db):
    assert _create(user, frozenset(), PLATFORM_ORG).pk is not None


def test_platform_deletes_without_holding_any_collection_key(user, collection):
    assert _delete(user, frozenset(), collection, PLATFORM_ORG).success is True
