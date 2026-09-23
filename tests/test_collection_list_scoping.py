"""The collections listing does not hand out another organization's drafts.

`SPEC-forms-permission-gates` CAP-3, collections only. The row-scope gate
closed single-row access; the listing still returned every organization's rows
to every caller.

The scope is a union rather than plain org ownership: this one resolver serves
both the admin listing and the public catalog page, and the forms GraphQL proxy
forwards `x-organization-id` on every operation, so plain ownership would empty
the catalog for any signed-in shopper. Published rows are already public.
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
from survey_collections.inputs import SurveyCollectionsListInput
from survey_collections.models import SurveyCollection
from survey_collections.schemas.queries.collections import CollectionsQuery

ORG_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
ORG_B = uuid.UUID("22222222-2222-2222-2222-222222222222")
PLATFORM_ORG = uuid.UUID("33333333-3333-3333-3333-333333333333")


class _Context:
    def __init__(self, organization_id):
        self.auth_context = (
            None
            if organization_id is None
            else AuthContext(
                user_id=UserId("keycloak-test"),
                organization_id=OrgId(organization_id),
                role_names=frozenset({"org-admin"}),
                perms=frozenset({"collections:read"}),
            )
        )


class _Info:
    def __init__(self, organization_id):
        self.context = _Context(organization_id)
        # `get_root_field_paths` / `has_any_under_prefix` read the selection set;
        # an empty one means "no facets requested", which is what we want here.
        self.selected_fields = []


@pytest.fixture(autouse=True)
def platform_org():
    previous = (platform._platform_org_id, platform._resolved)
    platform._platform_org_id = OrgId(PLATFORM_ORG)
    platform._resolved = True
    yield
    platform._platform_org_id, platform._resolved = previous


@pytest.fixture
def rows(db):
    """One draft and one published row per organization, plus a null-owned row."""
    return {
        "a_draft": SurveyCollection.objects.create(
            organization_id=ORG_A, status=SurveyCollection.STATUS_DRAFT
        ),
        "a_published": SurveyCollection.objects.create(
            organization_id=ORG_A, status=SurveyCollection.STATUS_PUBLISHED
        ),
        "b_draft": SurveyCollection.objects.create(
            organization_id=ORG_B, status=SurveyCollection.STATUS_DRAFT
        ),
        "b_published": SurveyCollection.objects.create(
            organization_id=ORG_B, status=SurveyCollection.STATUS_PUBLISHED
        ),
        "orphan_draft": SurveyCollection.objects.create(
            organization_id=None, status=SurveyCollection.STATUS_DRAFT
        ),
    }


def _list(organization_id):
    resolver = None
    for field in CollectionsQuery.__strawberry_definition__.fields:
        if field.name == "collections":
            resolver = field.base_resolver.wrapped_func
    assert resolver is not None
    result = resolver(
        CollectionsQuery(),
        _Info(organization_id),
        collections_list_input=SurveyCollectionsListInput(limit=50),
    )
    return {item.pk for item in result.items}, result.total


def test_another_organizations_draft_is_not_listed(rows):
    ids, total = _list(ORG_A)

    assert rows["b_draft"].pk not in ids
    assert total == len(ids)


def test_a_null_owned_draft_is_not_listed(rows):
    """The Apr-Sep 2026 backfill gap: a null owner belongs to nobody."""
    assert rows["orphan_draft"].pk not in _list(ORG_A)[0]


def test_the_caller_sees_its_own_rows_whatever_their_status(rows):
    ids = _list(ORG_A)[0]

    assert rows["a_draft"].pk in ids
    assert rows["a_published"].pk in ids


def test_the_caller_still_sees_other_organizations_published_rows(rows):
    """The catalog must not collapse for a signed-in shopper — the proxy sends
    the org header on the storefront query too."""
    assert rows["b_published"].pk in _list(ORG_A)[0]


def test_platform_sees_everything(rows):
    assert _list(PLATFORM_ORG)[0] == {row.pk for row in rows.values()}


def test_an_anonymous_caller_is_left_alone(rows):
    """Whether this listing should be published-only is the open question CAP-3
    is blocked on; narrowing the anonymous path would settle it by accident."""
    assert _list(None)[0] == {row.pk for row in rows.values()}
