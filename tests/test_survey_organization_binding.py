"""The owning organization of a survey is bound from the caller, not the client.

`SPEC-forms-permission-gates` CAP-1. `organization_id` used to be auto-generated
onto both survey input types and never set from the auth context, so a caller in
org A could create or update a row stamped org B.

These call the mutation resolver through the same decorator stack the GraphQL
layer uses, so the permission check and the binding are both exercised.
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

from surveys.inputs import SurveyCreateInput, SurveyUpdateInput
from surveys.models import Survey
from surveys.schemas.mutations.surveys import SurveyMutations

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
        self.auth_context = AuthContext(
            user_id=UserId(user.id),
            organization_id=OrgId(organization_id),
            role_names=frozenset({"org-admin"}),
            perms=frozenset({"surveys:create", "surveys:update"}),
        )


class _Info:
    def __init__(self, user, organization_id):
        self.context = _Context(user, organization_id)


@dataclasses.dataclass
class _LegacyCreateInput:
    """A create input that still carries `organization_id`, as the generated one
    did before it was excluded. Proves the resolver overrides the client's value
    rather than relying on the schema alone to withhold the field."""

    organization_id: Optional[uuid.UUID] = UNSET
    survey_type: Optional[str] = "survey"
    category_id: Optional[str] = UNSET
    translations: Optional[list] = UNSET
    external_reference: Optional[object] = UNSET
    prices: Optional[list] = UNSET


def _resolver(name):
    for field in SurveyMutations.__strawberry_definition__.fields:
        if field.name == name:
            return field.base_resolver.wrapped_func
    raise AssertionError(f"resolver not found: {name}")


def _create(user, organization_id, input_obj):
    return _resolver("create_survey")(
        SurveyMutations(), _Info(user, organization_id), input=input_obj
    ).survey


def test_organization_id_is_not_settable_on_either_input():
    """The generated input types used to expose `organizationId` outright."""
    for input_type in (SurveyCreateInput, SurveyUpdateInput):
        names = {f.name for f in input_type.__strawberry_definition__.fields}
        assert "organization_id" not in names, input_type.__name__


def test_create_binds_the_callers_organization_when_none_is_supplied(user):
    survey = _create(user, ORG_A, SurveyCreateInput(survey_type="survey"))

    assert Survey.objects.get(pk=survey.pk).organization_id == ORG_A


def test_create_overrides_an_organization_supplied_by_the_client(user):
    survey = _create(user, ORG_A, _LegacyCreateInput(organization_id=ORG_B))

    assert Survey.objects.get(pk=survey.pk).organization_id == ORG_A
