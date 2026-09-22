"""The owning organization of a collection is bound from the caller.

`SPEC-forms-permission-gates` CAP-1, the half task 106 did not reach.
`create_survey_collection` never set `organization_id`, so every collection
created through the app was null-owned — which migration 0040 had to repair and
which the CAP-2 row gate treats as a refusal.

These call the mutation resolver through the same decorator stack the GraphQL
layer uses.
"""
import dataclasses
import os
import uuid
from typing import Optional

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
django.setup()

import surveys.schemas.schema  # noqa: F401  (resolves the mutation import cycle)
from pkg_auth.authorization import AuthContext, OrgId, UserId
from strawberry import UNSET

from survey_collections.inputs import SurveyCollectionInput
from survey_collections.models import SurveyCollection
from survey_collections.schemas.mutations.collections import SurveyCollectionMutations

ORG_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
ORG_B = uuid.UUID("22222222-2222-2222-2222-222222222222")


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
        self.auth_context = (
            None
            if organization_id is None
            else AuthContext(
                user_id=UserId(user.id),
                organization_id=OrgId(organization_id),
                role_names=frozenset({"org-admin"}),
                perms=frozenset({"collections:create", "collections:update"}),
            )
        )


class _Info:
    def __init__(self, user, organization_id):
        self.context = _Context(user, organization_id)


@dataclasses.dataclass
class _LegacyCollectionInput:
    """An input that smuggles `organization_id` in, the way the generated survey
    inputs used to. Proves the resolver binds the caller's org rather than
    relying on the hand-written input type to withhold the field."""

    organization_id: Optional[uuid.UUID] = UNSET
    status: Optional[str] = UNSET
    category_id: Optional[str] = UNSET
    sponsor: Optional[int] = UNSET
    type: Optional[str] = UNSET
    cover_id: Optional[str] = UNSET
    thumb_id: Optional[str] = UNSET
    translations: Optional[list] = UNSET
    prices: Optional[list] = UNSET


def _resolver(name):
    for field in SurveyCollectionMutations.__strawberry_definition__.fields:
        if field.name == name:
            return field.base_resolver.wrapped_func
    raise AssertionError(f"resolver not found: {name}")


def _create(user, organization_id, input_obj=None):
    return _resolver("create_survey_collection")(
        SurveyCollectionMutations(),
        _Info(user, organization_id),
        input=input_obj if input_obj is not None else SurveyCollectionInput(),
    )


def test_the_input_type_does_not_expose_organization_id():
    names = {f.name for f in SurveyCollectionInput.__strawberry_definition__.fields}

    assert "organization_id" not in names


def test_create_binds_the_callers_organization(user):
    collection = _create(user, ORG_A)

    assert SurveyCollection.objects.get(pk=collection.pk).organization_id == ORG_A


def test_create_overrides_an_organization_supplied_by_the_client(user):
    collection = _create(user, ORG_A, _LegacyCollectionInput(organization_id=ORG_B))

    assert SurveyCollection.objects.get(pk=collection.pk).organization_id == ORG_A


def test_create_without_an_organization_context_is_refused(user):
    """RequireAuth proves identity only, and there is no check_permission on
    this resolver to have proven an org context. Creating a null-owned row
    instead would strand it behind the CAP-2 gate."""
    with pytest.raises(PermissionError):
        _create(user, None)

    assert not SurveyCollection.objects.exists()


def test_a_bound_collection_passes_the_row_scope_gate(user):
    """What the binding is for: ensure_in_org refuses a null owner outright."""
    from app.platform import ensure_in_org

    collection = _create(user, ORG_A)
    auth_ctx = _Info(user, ORG_A).context.auth_context

    ensure_in_org(collection, auth_ctx)  # does not raise

    with pytest.raises(PermissionError):
        ensure_in_org(collection, _Info(user, ORG_B).context.auth_context)
