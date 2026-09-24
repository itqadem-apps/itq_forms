"""The collections listing does not hand out another organization's drafts.

`SPEC-forms-permission-gates` CAP-3, collections only. The row-scope gate
closed single-row access; the listing still returned every organization's rows
to every caller.

The scope is plain org ownership. A union arm ("or anyone's published row") was
tried first, to keep the public catalog populated for a signed-in visitor; in
production it showed a tenant owning nothing all 40 of another organization's
published rows, which is the opposite of the intended behaviour. The catalog
page sends `status: published` itself, so the arm only ever carried the
cross-organization half.
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
    """One draft and one published row per organization, and the same pair
    null-owned — the Apr-Sep 2026 backfill gap left both statuses behind."""
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
        "orphan_published": SurveyCollection.objects.create(
            organization_id=None, status=SurveyCollection.STATUS_PUBLISHED
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


def test_a_null_owned_row_is_not_listed(rows):
    """The Apr-Sep 2026 backfill gap: a null owner belongs to nobody.

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
