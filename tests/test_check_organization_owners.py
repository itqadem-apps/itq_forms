"""The ownership check counts, and only counts.

`SPEC-forms-permission-gates` CAP-2 step 3. The point of the command is that it
is safe to run against production, so the test that matters most is the one
asserting it wrote nothing.
"""
import os
import uuid
from io import StringIO

import django
import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
django.setup()

from django.core.management import call_command

from accounts.models import Child, ChildGuardian
from survey_collections.models import SurveyCollection
from surveys.models import Survey

ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def rows(db):
    owned = Survey.objects.create(survey_type="survey", organization_id=ORG)
    stranded = Survey.objects.create(survey_type="assessment", organization_id=None)
    SurveyCollection.objects.create(organization_id=None)
    child = Child.objects.create(id="child-1", name="A child")
    # Three null owners, and only one of them is a defect. The blank role is
    # kept because the projection writes `""` when the event carries no role.
    ChildGuardian.objects.create(
        id="guardian-1", child=child, user_id="keycloak-test", organization_id=None
    )
    ChildGuardian.objects.create(
        id="guardian-2",
        child=child,
        user_id="keycloak-parent",
        role="guardian",
        organization_id=None,
    )
    ChildGuardian.objects.create(
        id="guardian-3",
        child=child,
        user_id="keycloak-specialist",
        role="supervisor",
        organization_id=None,
    )
    return {"owned": owned, "stranded": stranded}


def _run(**kwargs):
    out = StringIO()
    call_command("check_organization_owners", stdout=out, **kwargs)
    return out.getvalue()


def test_it_counts_the_stranded_rows(rows):
    output = _run()

    assert "surveys_survey" in output
    assert "1 null of       2" in output
    assert "survey_collections_surveycollection" in output
    assert "accounts_childguardian" in output


def test_it_breaks_surveys_down_by_type_and_status(rows):
    output = _run()

    # The stranded row is the assessment; the owned survey must not appear.
    assert "assessment" in output
    assert "survey       " not in output.split("by type and status:")[1]


def test_it_names_the_guardian_table_as_not_repairable_here(rows):
    assert "do not repair here" in _run()


def test_it_splits_the_guardian_nulls_by_role(rows):
    """The bare null count is not a defect count, and reading it as one sends
    the repair at the wrong table.

    A `guardian` row is meant to carry no organization — a parent's relation to
    their child is not organization-scoped — and `supervised_child_ids_for_org`
    filters on `role="supervisor"` anyway, so those nulls never reach the query
    they would under-grant. Only the supervisor row is evidence of anything.
    """
    output = _run()

    assert "role=supervisor" in output
    assert "under-grants submissions:read" in output
    assert "role=guardian" in output
    assert "not org-scoped" in output
    assert "role=(blank)" in output


def test_it_flags_rows_outside_the_gap_window(rows):
    """A null owner created after the CAP-1 binding is a second source, and the
    history in the docstring does not explain it."""
    Survey.objects.create(
        survey_type="survey", organization_id=None, created_at="2027-01-01T00:00:00Z"
    )

    assert "OUTSIDE the gap window" in _run()


def test_by_month_groups_by_creation_month(rows):
    assert "by month" in _run(by_month=True)


def test_it_writes_nothing(rows):
    before = {
        "surveys": list(Survey.objects.values_list("id", "organization_id").order_by("id")),
        "collections": list(
            SurveyCollection.objects.values_list("id", "organization_id").order_by("id")
        ),
        "guardians": list(
            ChildGuardian.objects.values_list("id", "organization_id").order_by("id")
        ),
    }

    _run(by_month=True)

    assert before == {
        "surveys": list(Survey.objects.values_list("id", "organization_id").order_by("id")),
        "collections": list(
            SurveyCollection.objects.values_list("id", "organization_id").order_by("id")
        ),
        "guardians": list(
            ChildGuardian.objects.values_list("id", "organization_id").order_by("id")
        ),
    }
