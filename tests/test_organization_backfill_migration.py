"""The 0040 repair must reach every stranded row and disturb nothing else.

Prod cannot run a management command, so the repair rides in as a data
migration. It runs unattended, on every environment, with nobody reading the
output — so what it does to already-owned rows matters as much as what it does
to the null ones. See `SPEC-forms-permission-gates` CAP-1/CAP-2.
"""
import importlib
import uuid

import pytest
from django.apps import apps as django_apps

from accounts.models import Child, ChildGuardian
from survey_collections.models import SurveyCollection
from surveys.models import Survey

migration = importlib.import_module(
    "surveys.migrations.0040_backfill_organization_id_gap"
)

ITQADEM = uuid.UUID("44444444-4444-4444-4444-444444444444")
OTHER_ORG = uuid.UUID("55555555-5555-5555-5555-555555555555")


@pytest.fixture(autouse=True)
def resolved_org(monkeypatch):
    """The real resolver reads the `acl` database, which tests don't populate."""
    monkeypatch.setattr(migration, "_resolve_org_id", lambda: ITQADEM)


def _run():
    migration.backfill(django_apps, None)


def test_a_stranded_survey_gets_the_itqadem_owner(db):
    survey = Survey.objects.create(survey_type="survey", organization_id=None)

    _run()

    survey.refresh_from_db()
    assert survey.organization_id == ITQADEM


def test_a_survey_that_already_has_an_owner_is_left_alone(db):
    """CAP-1 binds real owners on write; the repair must not overwrite them."""
    survey = Survey.objects.create(survey_type="survey", organization_id=OTHER_ORG)

    _run()

    survey.refresh_from_db()
    assert survey.organization_id == OTHER_ORG


def test_collections_and_guardians_are_repaired_too(db):
    """0035 covered all three tables and none of them bind on write yet."""
    collection = SurveyCollection.objects.create(organization_id=None)
    child = Child.objects.create(id="child-1", name="A child")
    guardian = ChildGuardian.objects.create(
        id="guardian-1", child=child, user_id="keycloak-test", organization_id=None
    )

    _run()

    collection.refresh_from_db()
    guardian.refresh_from_db()
    assert collection.organization_id == ITQADEM
    assert guardian.organization_id == str(ITQADEM)


def test_running_it_twice_changes_nothing_further(db):
    survey = Survey.objects.create(survey_type="survey", organization_id=None)
    kept = Survey.objects.create(survey_type="survey", organization_id=OTHER_ORG)

    _run()
    _run()

    survey.refresh_from_db()
    kept.refresh_from_db()
    assert survey.organization_id == ITQADEM
    assert kept.organization_id == OTHER_ORG


def test_a_repaired_row_is_reachable_again_through_the_cap_2_gate(db):
    """The point of the repair: ensure_in_org refuses a null owner outright."""
    from pkg_auth.authorization import AuthContext, OrgId, UserId
    from app.platform import ensure_in_org

    survey = Survey.objects.create(survey_type="survey", organization_id=None)
    auth_ctx = AuthContext(
        user_id=UserId("keycloak-test"),
        organization_id=OrgId(ITQADEM),
        role_names=frozenset({"org-admin"}),
        perms=frozenset({"surveys:read"}),
    )

    with pytest.raises(PermissionError):
        ensure_in_org(survey, auth_ctx)

    _run()
    survey.refresh_from_db()

    ensure_in_org(survey, auth_ctx)  # no longer raises
