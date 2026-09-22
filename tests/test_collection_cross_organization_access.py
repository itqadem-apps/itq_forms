"""A collection owned by another organization is out of reach.

`SPEC-forms-permission-gates` CAP-2, extended to collections. The collection
write resolvers check the permission key, but nothing compared the loaded row's
`organization_id` to the caller's — so an org A admin holding `collections:*`
could edit, delete or re-populate org B's collection by id.

Membership is gated on both sides: `add_survey_to_collection` joins two rows,
and either one belonging to another organization is a cross-tenant write.
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
from surveys.models import Survey

ORG_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
ORG_B = uuid.UUID("22222222-2222-2222-2222-222222222222")
PLATFORM_ORG = uuid.UUID("33333333-3333-3333-3333-333333333333")

#: Any writable scalar; `sponsor` is a plain integer column with no side effects.
EDITED_SPONSOR = 99

# Every key these resolvers can ask for, so a denial can only come from the
# row-scope gate and never from a missing permission.
ALL_KEYS = frozenset(
    f"{kind}:{action}"
    for kind in ("surveys", "assessments", "curriculums", "exams", "forms", "collections")
    for action in ("create", "read", "update", "delete")
)


class _Identity:
    def __init__(self, user):
        self.subject_str = user.id
        self.email_str = user.email
        self.preferred_username = user.username
        self.first_name = ""
        self.last_name = ""


class _Context:
    def __init__(self, user, organization_id):
        self.identity = _Identity(user)
        self.auth_context = AuthContext(
            user_id=UserId(user.id),
            organization_id=OrgId(organization_id),
            role_names=frozenset({"org-admin"}),
            perms=ALL_KEYS,
        )


class _Info:
    def __init__(self, user, organization_id):
        self.context = _Context(user, organization_id)


@pytest.fixture(autouse=True)
def platform_org():
    previous = (platform._platform_org_id, platform._resolved)
    platform._platform_org_id = OrgId(PLATFORM_ORG)
    platform._resolved = True
    yield
    platform._platform_org_id, platform._resolved = previous


@pytest.fixture
def their_collection(db):
    return SurveyCollection.objects.create(organization_id=ORG_B)


@pytest.fixture
def their_survey(db):
    return Survey.objects.create(survey_type="survey", organization_id=ORG_B)


@pytest.fixture
def my_survey(db):
    return Survey.objects.create(survey_type="survey", organization_id=ORG_A)


def _resolver(name):
    for field in SurveyCollectionMutations.__strawberry_definition__.fields:
        if field.name == name:
            return field.base_resolver.wrapped_func
    raise AssertionError(f"resolver not found: {name}")


def _update(user, org, collection):
    return _resolver("update_survey_collection")(
        SurveyCollectionMutations(),
        _Info(user, org),
        id=str(collection.pk),
        input=SurveyCollectionInput(sponsor=EDITED_SPONSOR),
    )


def _delete(user, org, collection):
    return _resolver("delete_survey_collection")(
        SurveyCollectionMutations(), _Info(user, org), id=str(collection.pk)
    )


def _add(user, org, collection, survey):
    return _resolver("add_survey_to_collection")(
        SurveyCollectionMutations(),
        _Info(user, org),
        collection_id=str(collection.pk),
        survey_id=str(survey.pk),
    )


def _remove(user, org, collection, survey):
    return _resolver("remove_survey_from_collection")(
        SurveyCollectionMutations(),
        _Info(user, org),
        collection_id=str(collection.pk),
        survey_id=str(survey.pk),
    )


# --- another organization's collection is refused --------------------------

def test_update_of_another_organizations_collection_is_refused(user, their_collection):
    with pytest.raises(PermissionError):
        _update(user, ORG_A, their_collection)

    their_collection.refresh_from_db()
    assert their_collection.sponsor != EDITED_SPONSOR


def test_delete_of_another_organizations_collection_is_refused(user, their_collection):
    with pytest.raises(PermissionError):
        _delete(user, ORG_A, their_collection)

    their_collection.refresh_from_db()
    assert their_collection.deleted_at is None


def test_adding_to_another_organizations_collection_is_refused(user, their_collection, my_survey):
    with pytest.raises(PermissionError):
        _add(user, ORG_A, their_collection, my_survey)

    assert their_collection.assessments.count() == 0


def test_removing_from_another_organizations_collection_is_refused(
    user, their_collection, their_survey
):
    their_collection.assessments.add(their_survey)

    with pytest.raises(PermissionError):
        _remove(user, ORG_A, their_collection, their_survey)

    assert their_collection.assessments.count() == 1


def test_adding_another_organizations_survey_to_my_collection_is_refused(user, their_survey, db):
    mine = SurveyCollection.objects.create(organization_id=ORG_A)

    with pytest.raises(PermissionError):
        _add(user, ORG_A, mine, their_survey)

    assert mine.assessments.count() == 0


def test_a_null_owned_collection_is_refused(user, db):
    """The Apr-Sep 2026 backfill gap: a null owner belongs to nobody, not everybody."""
    orphan = SurveyCollection.objects.create(organization_id=None)

    with pytest.raises(PermissionError):
        _update(user, ORG_A, orphan)


# --- the owner still gets through ------------------------------------------

def test_the_owner_updates_its_own_collection(user, their_collection):
    assert _update(user, ORG_B, their_collection).sponsor == EDITED_SPONSOR


def test_the_owner_adds_its_own_survey(user, their_collection, their_survey):
    assert _add(user, ORG_B, their_collection, their_survey).assessments.count() == 1


def test_the_owner_deletes_its_own_collection(user, their_collection):
    assert _delete(user, ORG_B, their_collection).success is True


# --- the platform org bypasses the gate ------------------------------------

def test_platform_updates_any_organizations_collection(user, their_collection):
    assert _update(user, PLATFORM_ORG, their_collection).sponsor == EDITED_SPONSOR


def test_platform_adds_any_organizations_survey(user, their_collection, their_survey):
    assert _add(user, PLATFORM_ORG, their_collection, their_survey).assessments.count() == 1


def test_platform_deletes_any_organizations_collection(user, their_collection):
    assert _delete(user, PLATFORM_ORG, their_collection).success is True
