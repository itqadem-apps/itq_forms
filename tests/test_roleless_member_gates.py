"""Holding an `AuthContext` is not being staff.

`estate:AD-29` makes every user a roleless member of Itqadem, so an in-org
context with no keys is an ordinary customer. Gate-audit rows #1, #2 and #4
(`.agent/planning/audits/roleless-membership-gates.md`): the listings,
`Query.survey` and upload start used to treat any context as staff.
Unpublished rows now need the kind's read key (`collections:read` for
collections), and upload start needs a permission. Row #3 (story 1.17):
creating a collection needs `collections:create`.
"""
import logging
import os
import uuid

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
django.setup()

import surveys.schemas.schema  # noqa: F401  (resolves the mutation import cycle)
from pkg_auth.authorization import AuthContext, OrgId, UserId

import app.platform as platform
from media.access import Viewer
from media.profiles import FORMS_THUMB
from media.views import _may_edit
from survey_collections.inputs import SurveyCollectionInput, SurveyCollectionsListInput
from survey_collections.models import SurveyCollection
from survey_collections.schemas.mutations.collections import SurveyCollectionMutations
from survey_collections.schemas.queries.collections import CollectionsQuery
from surveys.inputs import SurveysListInput
from surveys.models import Survey
from surveys.schemas.queries.survey import SurveyQuery
from surveys.schemas.queries.surveys import SurveysQuery

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_ORG = uuid.UUID("22222222-2222-2222-2222-222222222222")
PLATFORM_ORG = uuid.UUID("33333333-3333-3333-3333-333333333333")


def _ctx(perms=(), org=ORG, roles=()):
    """Roles and keys are set independently: the gates read keys only, so most
    tests give a keyed caller no role at all."""
    return AuthContext(
        user_id=UserId("keycloak-test"),
        organization_id=OrgId(org),
        role_names=frozenset(roles),
        perms=frozenset(perms),
    )


class _Context:
    def __init__(self, auth_context):
        self.auth_context = auth_context


class _Info:
    def __init__(self, auth_context):
        self.context = _Context(auth_context)
        self.selected_fields = []


@pytest.fixture(autouse=True)
def platform_org():
    previous = (platform._platform_org_id, platform._resolved)
    platform._platform_org_id = OrgId(PLATFORM_ORG)
    platform._resolved = True
    yield
    platform._platform_org_id, platform._resolved = previous


@pytest.fixture
def survey_rows(db):
    return {
        "draft_survey": Survey.objects.create(
            organization_id=ORG, survey_type="survey", status=Survey.STATUS_DRAFT
        ),
        "draft_exam": Survey.objects.create(
            organization_id=ORG, survey_type="exam", status=Survey.STATUS_DRAFT
        ),
        "published_survey": Survey.objects.create(
            organization_id=ORG, survey_type="survey", status=Survey.STATUS_PUBLISHED
        ),
        "published_exam": Survey.objects.create(
            organization_id=ORG, survey_type="exam", status=Survey.STATUS_PUBLISHED
        ),
    }


@pytest.fixture
def collections(db):
    return {
        "draft": SurveyCollection.objects.create(
            organization_id=ORG, status=SurveyCollection.STATUS_DRAFT
        ),
        "published": SurveyCollection.objects.create(
            organization_id=ORG, status=SurveyCollection.STATUS_PUBLISHED
        ),
    }


def _resolver(query_cls, name):
    for field in query_cls.__strawberry_definition__.fields:
        if field.name == name:
            return field.base_resolver.wrapped_func
    raise AssertionError(f"resolver not found: {name}")


def _list_surveys(auth_ctx):
    result = _resolver(SurveysQuery, "surveys")(
        SurveysQuery(), _Info(auth_ctx), surveys_list_input=SurveysListInput(limit=50)
    )
    return {item.pk for item in result.items}


def _list_collections(auth_ctx):
    result = _resolver(CollectionsQuery, "collections")(
        CollectionsQuery(),
        _Info(auth_ctx),
        collections_list_input=SurveyCollectionsListInput(limit=50),
    )
    return {item.pk for item in result.items}


def _read(auth_ctx, survey):
    return SurveyQuery().survey(_Info(auth_ctx), id=str(survey.pk))


def _ids(rows, *names):
    return {rows[name].pk for name in names}


# --- listings ---------------------------------------------------------------

def test_a_roleless_member_lists_only_published_surveys(survey_rows):
    assert _list_surveys(_ctx()) == _ids(survey_rows, "published_survey", "published_exam")


def test_a_roleless_member_lists_only_published_collections(collections):
    assert _list_collections(_ctx()) == _ids(collections, "published")


def test_staff_list_the_drafts_of_the_kinds_they_read(survey_rows):
    assert _list_surveys(_ctx({"surveys:read"}, roles={"org-admin"})) == _ids(
        survey_rows, "draft_survey", "published_survey", "published_exam"
    )


def test_two_read_keys_list_both_draft_kinds(survey_rows):
    assert _list_surveys(_ctx({"surveys:read", "exams:read"})) == {
        row.pk for row in survey_rows.values()
    }


def test_a_read_key_does_not_list_another_organizations_draft(survey_rows):
    other_draft = Survey.objects.create(
        organization_id=OTHER_ORG, survey_type="survey", status=Survey.STATUS_DRAFT
    )
    assert other_draft.pk not in _list_surveys(_ctx({"surveys:read"}))


def test_collections_read_lists_draft_collections(collections):
    assert _list_collections(_ctx({"collections:read"})) == _ids(collections, "draft", "published")


def test_platform_listing_is_unchanged(survey_rows, collections):
    platform_ctx = _ctx({"surveys:read"}, org=PLATFORM_ORG, roles={"platform-admin"})
    assert _list_surveys(platform_ctx) == {row.pk for row in survey_rows.values()}
    assert _list_collections(platform_ctx) == {row.pk for row in collections.values()}


def test_anonymous_listing_is_unchanged(survey_rows, collections):
    assert _list_surveys(None) == _ids(survey_rows, "published_survey", "published_exam")
    assert _list_collections(None) == _ids(collections, "published")


# --- by id ------------------------------------------------------------------

def test_a_roleless_member_cannot_read_a_draft_by_id(survey_rows):
    assert _read(_ctx(), survey_rows["draft_survey"]) is None


def test_staff_read_a_draft_of_their_kind_by_id(survey_rows):
    assert _read(_ctx({"surveys:read"}), survey_rows["draft_survey"]) == survey_rows["draft_survey"]


def test_another_kinds_read_key_does_not_open_a_draft(survey_rows):
    assert _read(_ctx({"surveys:read"}), survey_rows["draft_exam"]) is None


def test_a_roleless_member_reads_a_published_survey_by_id(survey_rows):
    assert _read(_ctx(), survey_rows["published_survey"]) == survey_rows["published_survey"]


def test_platform_reads_a_draft_by_id(survey_rows):
    assert _read(_ctx({"surveys:read"}, org=PLATFORM_ORG, roles={"platform-admin"}), survey_rows["draft_exam"]) == survey_rows["draft_exam"]


def test_anonymous_read_by_id_is_unchanged(survey_rows):
    assert _read(None, survey_rows["draft_survey"]) is None
    assert _read(None, survey_rows["published_survey"]) == survey_rows["published_survey"]


# --- upload start -----------------------------------------------------------

def _may_upload(auth_ctx, context):
    return _may_edit(Viewer(user_id="keycloak-test", auth_context=auth_ctx), context, FORMS_THUMB)


def test_a_roleless_member_cannot_start_an_upload_without_ids(caplog):
    with caplog.at_level(logging.INFO, logger="media.views"):
        assert _may_upload(_ctx(), {}) is False
    assert "Upload refused" in caplog.text


def test_a_collection_upload_needs_collections_update(collections, caplog):
    context = {"collectionId": str(collections["draft"].pk)}
    with caplog.at_level(logging.INFO, logger="media.views"):
        assert _may_upload(_ctx({"collections:read"}), context) is False
    assert "Upload refused" in caplog.text


def test_staff_may_start_an_upload(collections):
    assert _may_upload(_ctx({"surveys:create"}), {}) is True
    assert _may_upload(_ctx({"exams:create"}), {}) is True
    assert _may_upload(_ctx({"collections:create"}), {}) is True
    assert _may_upload(
        _ctx({"collections:update"}), {"collectionId": str(collections["draft"].pk)}
    ) is True


# --- collection create ------------------------------------------------------

def _create_collection(auth_ctx, **fields):
    fn = SurveyCollectionMutations.create_survey_collection
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn(
        SurveyCollectionMutations(), _Info(auth_ctx),
        input=SurveyCollectionInput(**fields), django_user=None,
    )


@pytest.mark.parametrize(
    "auth_ctx",
    [
        pytest.param(_ctx(), id="roleless"),
        pytest.param(_ctx({"collections:read", "collections:update", "collections:delete", "surveys:create"}), id="wrong-keys"),
        pytest.param(_ctx(org=PLATFORM_ORG, roles={"platform-admin"}), id="platform-without-key"),
    ],
)
def test_creating_a_collection_needs_collections_create(db, auth_ctx):
    with pytest.raises(PermissionError, match="collections:create"):
        _create_collection(auth_ctx, status="draft")
    assert not SurveyCollection.objects.exists()


def test_the_create_refusal_comes_before_claim_validation(db):
    with pytest.raises(PermissionError, match="collections:create"):
        _create_collection(_ctx(), thumb_id=str(uuid.uuid4()))
    assert not SurveyCollection.objects.exists()


def test_create_without_a_context_is_still_refused(db):
    with pytest.raises(PermissionError, match="X-Organization-Id"):
        _create_collection(None, status="draft")
    assert not SurveyCollection.objects.exists()


def test_staff_create_a_collection_in_their_organization(db):
    collection = _create_collection(_ctx({"collections:create"}), status="draft")
    assert SurveyCollection.objects.get().pk == collection.pk
    assert collection.organization_id == ORG
    assert collection.status == "draft"
