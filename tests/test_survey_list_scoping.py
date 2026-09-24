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
    """One draft and one published row per organization, and the same pair
    null-owned — the Apr-Sep 2026 backfill gap left both statuses behind."""
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
        "orphan_published": Survey.objects.create(
            organization_id=None, status=Survey.STATUS_PUBLISHED
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
    exist in production and `ensure_in_org` already refuses them on read.

    Status does not enter into it — a null-owned *published* row is no more
    org A's than a draft is — which is what separates this gate from the
    unscoped public set below, where the same row is visible."""
    ids = _list(ORG_A)[0]

    assert rows["orphan_draft"].pk not in ids
    assert rows["orphan_published"].pk not in ids


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


def test_an_unscoped_caller_sees_only_published_rows(rows):
    """Ruled 2026-09-24, closing the open question CAP-3 was blocked on: a
    caller with no ``AuthContext`` gets the **public set** — published rows,
    any organization.

    This test asserted the opposite until that ruling, on the grounds that
    narrowing the path would settle the question by accident. It is settled
    now, deliberately.

    ``orphan_published`` is in the expected set as a *consequence* of the
    ruling, not as a policy ruled on its own: a row with a null owner is
    published, so the public set takes it. That is what production does today
    too, and it is the odd corner where a row no tenant can reach is
    nonetheless publicly listed. Repairing those owners is task 107, not this
    gate's job.
    """
    assert _list(None)[0] == {
        rows["a_published"].pk,
        rows["b_published"].pk,
        rows["orphan_published"].pk,
    }


def test_an_unscoped_caller_sees_no_drafts(rows):
    """The read half of the inverted gate, from
    ``stories/estate/forms-unresolved-context-is-unscoped.md``.

    ``OptionalAuthContextMiddleware`` yields ``None`` for *authenticated*
    callers too — a stale ``organization-id`` cookie naming an org the user has
    left reaches this through the ordinary UI, because the forms proxy forwards
    the cookie on every operation. Such a caller used to read every
    organization's rows in every status: strictly more than a current member of
    either org.

    There is deliberately no second branch to exercise. The middleware hands
    the resolver the same ``None`` an anonymous caller produces, which is the
    point — one path, so the unresolved case cannot drift back above the
    anonymous one.
    """
    ids = _list(None)[0]

    assert rows["a_draft"].pk not in ids
    assert rows["b_draft"].pk not in ids
    assert rows["orphan_draft"].pk not in ids
