"""A forms row owned by another organization is out of reach.

`SPEC-forms-permission-gates` CAP-2. `itq_forms` had no row-scope gate in any
form: `update_survey` and `delete_survey` checked the permission key and
nothing else, so a caller in org A holding every `forms:*`/`surveys:*` key
could address org B's rows by id.

These call the resolvers through the same decorator stack the GraphQL layer
uses, so the permission check and the row-scope gate are both exercised.
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
from surveys.inputs import SurveyUpdateInput
from surveys.models import Survey
from surveys.schemas.mutations.surveys import SurveyMutations
from surveys.schemas.queries.survey import SurveyQuery

ORG_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
ORG_B = uuid.UUID("22222222-2222-2222-2222-222222222222")
PLATFORM_ORG = uuid.UUID("33333333-3333-3333-3333-333333333333")

# Every key the survey resolvers can ask for, so a denial can only come from
# the row-scope gate and never from a missing permission.
ALL_KEYS = frozenset(
    f"{kind}:{action}"
    for kind in ("surveys", "assessments", "curriculums", "exams", "forms", "collections")
    for action in ("create", "read", "update", "delete")
) | {"submissions:read"}


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
    """Pin the platform org id that `is_platform_context` compares against."""
    previous = (platform._platform_org_id, platform._resolved)
    platform._platform_org_id = OrgId(PLATFORM_ORG)
    platform._resolved = True
    yield
    platform._platform_org_id, platform._resolved = previous


@pytest.fixture
def org_b_survey(db):
    return Survey.objects.create(survey_type="survey", organization_id=ORG_B)


def _resolver(name):
    for field in SurveyMutations.__strawberry_definition__.fields:
        if field.name == name:
            return field.base_resolver.wrapped_func
    raise AssertionError(f"resolver not found: {name}")


def _read(user, org, survey):
    return SurveyQuery().survey(_Info(user, org), id=str(survey.pk))


def _update(user, org, survey):
    return _resolver("update_survey")(
        SurveyMutations(),
        _Info(user, org),
        input=SurveyUpdateInput(id=survey.pk),
    )


def _delete(user, org, survey):
    return _resolver("delete_survey")(
        SurveyMutations(), _Info(user, org), id=str(survey.pk)
    )


# --- a tenant caller in another org is refused -----------------------------

def test_read_of_another_organizations_survey_is_refused(user, org_b_survey):
    with pytest.raises(PermissionError):
        _read(user, ORG_A, org_b_survey)


def test_update_of_another_organizations_survey_is_refused(user, org_b_survey):
    with pytest.raises(PermissionError):
        _update(user, ORG_A, org_b_survey)


def test_delete_of_another_organizations_survey_is_refused(user, org_b_survey):
    with pytest.raises(PermissionError):
        _delete(user, ORG_A, org_b_survey)

    assert Survey.objects.filter(pk=org_b_survey.pk).exists()


# --- the owning org still reaches its own row ------------------------------

def test_the_owning_organization_still_reads_its_own_survey(user, org_b_survey):
    assert _read(user, ORG_B, org_b_survey).pk == org_b_survey.pk


def test_the_owning_organization_still_updates_its_own_survey(user, org_b_survey):
    assert _update(user, ORG_B, org_b_survey).success is True


# --- the platform org bypasses the gate ------------------------------------

def test_platform_reads_any_organizations_survey(user, org_b_survey):
    assert _read(user, PLATFORM_ORG, org_b_survey).pk == org_b_survey.pk


def test_platform_updates_any_organizations_survey(user, org_b_survey):
    assert _update(user, PLATFORM_ORG, org_b_survey).success is True


def test_platform_deletes_any_organizations_survey(user, org_b_survey):
    assert _delete(user, PLATFORM_ORG, org_b_survey).success is True
    assert not Survey.objects.filter(pk=org_b_survey.pk).exists()


# --- a row with no owner is not reachable by a tenant ----------------------

def test_a_survey_with_no_organization_is_refused(user, db):
    """`organization_id` is nullable and rows predating the CAP-1 binding can
    be null; the ported gate treats a null owner as a refusal, exactly as the
    itq_courses reference does."""
    orphan = Survey.objects.create(survey_type="survey", organization_id=None)

    with pytest.raises(PermissionError):
        _read(user, ORG_A, orphan)


def test_the_anonymous_read_path_is_untouched(org_b_survey):
    """No auth context — the detail read keeps its current behaviour. Whether
    it is a public catalog endpoint is the CAP-3 open question."""

    class _Anon:
        context = type("C", (), {"auth_context": None, "identity": None})()

    assert SurveyQuery().survey(_Anon(), id=str(org_b_survey.pk)).pk == org_b_survey.pk
