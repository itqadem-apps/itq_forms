"""forms:AD-15 — the legacy section jump is refused at the API.

The solver never honoured `submit_action="jump"` or `submit_action_target`, so
an author who set them got a survey that ignored them silently. The columns
stay (dropping them is deferred); what changes is that `SectionInput` can no
longer write a value into them. The refusal is a dict `ValidationError`, which
`handle_django_errors=True` turns into an `OperationInfo` naming each field.

Most call the resolver body directly with the strawberry/permission decorators
unwrapped, like `test_question_mutations`; the last two run the real GraphQL
mutation so the client-facing `OperationInfo` shape is pinned too.
"""

import pytest
from django.core.exceptions import ValidationError
from pkg_auth.authorization import AuthContext, OrgId, UserId
from strawberry import UNSET

from conftest import ORG

from surveys.inputs import SectionInput
from surveys.models import Section
from surveys.schemas.mutations.sections import SectionMutations


def _resolver(name):
    fn = getattr(SectionMutations, name)
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def _create(survey, **fields):
    return _resolver("create_section")(
        SectionMutations(), None, survey_id=str(survey.id), input=SectionInput(**fields), django_user=None,
    )


def _update(section, **fields):
    return _resolver("update_section")(
        SectionMutations(), None, id=str(section.id), input=SectionInput(**fields), django_user=None,
    )


def test_create_with_next_still_writes_a_row(survey):
    section = _create(survey, title="Plain", submit_action="next")
    assert section.submit_action == Section.SUBMIT_ACTION_NEXT
    assert section.submit_action_target is None


def test_create_with_jump_is_refused_on_submit_action_and_writes_nothing(survey):
    before = Section.objects.count()
    with pytest.raises(ValidationError) as excinfo:
        _create(survey, title="Jumper", submit_action="jump")
    assert set(excinfo.value.message_dict) == {"submit_action"}
    assert Section.objects.count() == before


def test_create_with_a_target_is_refused_on_submit_action_target(survey, section):
    before = Section.objects.count()
    with pytest.raises(ValidationError) as excinfo:
        _create(survey, title="Targeted", submit_action_target_id=section.id)
    assert set(excinfo.value.message_dict) == {"submit_action_target"}
    assert Section.objects.count() == before


def test_jump_and_target_together_name_both_fields(survey, section):
    before = Section.objects.count()
    with pytest.raises(ValidationError) as excinfo:
        _create(survey, submit_action="jump", submit_action_target_id=section.id)
    assert set(excinfo.value.message_dict) == {"submit_action", "submit_action_target"}
    assert Section.objects.count() == before


def test_update_with_jump_is_refused_and_leaves_the_row_alone(survey, section):
    other = Section.objects.create(survey=survey, title="Other")
    with pytest.raises(ValidationError) as excinfo:
        _update(section, title="Renamed", submit_action="jump", submit_action_target_id=other.id)
    assert set(excinfo.value.message_dict) == {"submit_action", "submit_action_target"}

    section.refresh_from_db()
    assert (section.title, section.submit_action, section.submit_action_target_id) == (
        "Section 1", Section.SUBMIT_ACTION_NEXT, None,
    )


def test_update_with_a_target_is_refused_on_submit_action_target(survey, section):
    other = Section.objects.create(survey=survey, title="Other")
    with pytest.raises(ValidationError) as excinfo:
        _update(section, submit_action_target_id=other.id)
    assert set(excinfo.value.message_dict) == {"submit_action_target"}


@pytest.mark.parametrize("target", [None, UNSET])
def test_a_null_or_absent_target_is_accepted(survey, section, target):
    """Every legacy row carries a null target, so a client echoing it back must
    not be refused — nor crash on a lookup of pk=None."""
    updated = _update(section, title="Kept", submit_action="next", submit_action_target_id=target)
    assert updated.submit_action_target is None

    created = _create(survey, title="New", submit_action_target_id=target)
    assert created.submit_action_target is None


def test_an_explicit_null_clears_a_stored_target(survey, section):
    """The one write path left for the column: a client clearing a target that
    a row already holds. An absent field must leave it alone."""
    other = Section.objects.create(survey=survey, title="Other")
    Section.objects.filter(pk=section.pk).update(submit_action_target=other)

    _update(section, title="Untouched target")
    section.refresh_from_db()
    assert section.submit_action_target_id == other.id

    _update(section, submit_action_target_id=None)
    section.refresh_from_db()
    assert section.submit_action_target_id is None


class _Identity:
    def __init__(self, user):
        self.subject_str = user.id
        self.email_str = user.email
        self.preferred_username = user.username
        self.first_name = ""
        self.last_name = ""


class _Context:
    def __init__(self, user):
        self.request = None
        self.identity = _Identity(user)
        self.currency = None
        self.auth_context = AuthContext(
            user_id=UserId(user.id),
            organization_id=OrgId(ORG),
            role_names=frozenset({"org-admin"}),
            perms=frozenset({"surveys:update"}),
        )


CREATE = """
mutation Create($survey: ID!, $input: SectionInput!) {
  createSection(surveyId: $survey, input: $input) {
    __typename
    ... on SectionType { id }
    ... on OperationInfo { messages { field kind } }
  }
}
"""

UPDATE = """
mutation Update($id: ID!, $input: SectionInput!) {
  updateSection(id: $id, input: $input) {
    __typename
    ... on SectionType { id }
    ... on OperationInfo { messages { field kind } }
  }
}
"""


def _run(user, document, **variables):
    from surveys import schema as schema_module

    result = schema_module.schema.execute_sync(
        document, variable_values=variables, context_value=_Context(user)
    )
    assert result.errors is None, result.errors
    return result.data


def test_create_refusal_reaches_the_client_as_named_field_errors(user, survey, section):
    before = Section.objects.count()
    payload = _run(
        user, CREATE, survey=str(survey.id),
        input={"title": "Jumper", "submitAction": "jump", "submitActionTargetId": section.id},
    )["createSection"]

    assert payload["__typename"] == "OperationInfo", payload
    assert {m["field"] for m in payload["messages"]} == {"submitAction", "submitActionTarget"}
    assert {m["kind"] for m in payload["messages"]} == {"VALIDATION"}
    assert Section.objects.count() == before


def test_update_refusal_reaches_the_client_as_named_field_errors(user, survey, section):
    payload = _run(user, UPDATE, id=str(section.id), input={"submitAction": "jump"})["updateSection"]

    assert payload["__typename"] == "OperationInfo", payload
    assert [m["field"] for m in payload["messages"]] == ["submitAction"]
    section.refresh_from_db()
    assert section.submit_action == Section.SUBMIT_ACTION_NEXT
