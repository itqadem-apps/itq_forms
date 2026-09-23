"""The surveys listing hands out only the caller organization's own rows.

`SPEC-forms-permission-gates` CAP-3, the surveys half. The row-scope gate
(CAP-2) already refuses single-row access, but the listing still returned every
organization's rows to every caller — verified in production 2026-09-23, where
a tenant saw all 142 surveys and could open only its own 133.

Same plain-ownership scope as the collections listing. A union arm ("or
anyone's published row") shipped first and was measured in production showing a
tenant that owns no surveys all 40 of another organization's published rows;
educational resources belong to the organization that published them, so the
arm was removed.
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
from surveys.inputs import SurveysListInput
from surveys.models import Survey
from surveys.schemas.queries.surveys import SurveysQuery

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
                perms=frozenset({"surveys:read"}),
            )
        )


class _Info:
    def __init__(self, organization_id):
        self.context = _Context(organization_id)
        # An empty selection set means "no facets requested".
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
        "a_draft": Survey.objects.create(
            organization_id=ORG_A, status=Survey.STATUS_DRAFT
        ),
        "a_published": Survey.objects.create(
            organization_id=ORG_A, status=Survey.STATUS_PUBLISHED
        ),
        "b_draft": Survey.objects.create(
            organization_id=ORG_B, status=Survey.STATUS_DRAFT
        ),
        "b_published": Survey.objects.create(
            organization_id=ORG_B, status=Survey.STATUS_PUBLISHED
        ),
        "orphan_draft": Survey.objects.create(
            organization_id=None, status=Survey.STATUS_DRAFT
        ),
    }


def _list(organization_id):
    resolver = None
    for field in SurveysQuery.__strawberry_definition__.fields:
        if field.name == "surveys":
            resolver = field.base_resolver.wrapped_func
    assert resolver is not None
    result = resolver(
        SurveysQuery(),
        _Info(organization_id),
        surveys_list_input=SurveysListInput(limit=50),
    )
    return {item.pk for item in result.items}, result.total


def test_another_organizations_draft_is_not_listed(rows):
    ids, total = _list(ORG_A)

    assert rows["b_draft"].pk not in ids
    assert total == len(ids)


def test_a_null_owned_row_is_not_listed(rows):
    """The May-Jun 2026 gap: a null owner belongs to nobody. Nine such rows
    exist in production and `ensure_in_org` already refuses them on read."""
    assert rows["orphan_draft"].pk not in _list(ORG_A)[0]


def test_the_caller_sees_its_own_rows_whatever_their_status(rows):
    ids = _list(ORG_A)[0]

    assert rows["a_draft"].pk in ids
    assert rows["a_published"].pk in ids


def test_another_organizations_published_row_is_not_listed(rows):
    """Content belongs to the organization that published it: a tenant that
    owns nothing sees nothing, catalog page included."""
    assert rows["b_published"].pk not in _list(ORG_A)[0]


def test_platform_sees_everything(rows):
    assert _list(PLATFORM_ORG)[0] == {row.pk for row in rows.values()}


def test_an_anonymous_caller_is_left_alone(rows):
    """Whether this listing should be published-only is the open question CAP-3
    is blocked on; narrowing the anonymous path would settle it by accident."""
    assert _list(None)[0] == {row.pk for row in rows.values()}
