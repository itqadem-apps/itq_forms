"""``userSurvey`` must not hand one tenant another tenant's submissions.

The resolver used to branch ``objects.all() if is_admin else own``, where
``is_admin`` was true for a platform context *or* for any holder of
``submissions:read``. The second branch had no organization predicate, so the
first clinic admin granted that key would have read every clinic's data.

Access for an organization is derived from the child's active supervisor
relation — the consent path the guardian approved and can revoke — so these
tests pin the derivation, not a stored column.
"""
import pytest
from pkg_auth.authorization import MissingPermission

from accounts.models import Child, ChildGuardian
from app.permissions import Permission
from user_surveys.models import UserSurvey
from user_surveys.schemas.queries import user_surveys as module


ORG = "org-1"
OTHER_ORG = "org-2"


class _AuthContext:
    def __init__(self, organization_id=None, permissions=()):
        self.organization_id = organization_id
        self._permissions = set(permissions)

    def require(self, key):
        if key not in self._permissions:
            raise MissingPermission(key)


class _Info:
    def __init__(self, auth_context):
        self.context = type("Ctx", (), {"auth_context": auth_context})()


@pytest.fixture
def platform(monkeypatch):
    """Route ``is_platform_context`` off the auth context, not the org table."""
    monkeypatch.setattr(
        module,
        "is_platform_context",
        lambda auth_ctx: getattr(auth_ctx, "organization_id", None) == "platform",
    )


def _child(child_id, org=ORG, *, role="supervisor", status="active"):
    child = Child.objects.create(id=child_id, name=child_id)
    ChildGuardian.objects.create(
        id=f"rel-{child_id}-{org}",
        child=child,
        user_id="staff-1",
        role=role,
        status=status,
        organization_id=org,
    )
    return child


def _submission(user, child=None):
    return UserSurvey.objects.create(user=user, child=child)


def _visible(auth_ctx, django_user, platform_flag=None):
    return set(module._submissions_visible_to(_Info(auth_ctx), django_user))


def test_platform_context_sees_every_submission(user, user2, platform):
    mine = _submission(user)
    theirs = _submission(user2, _child("child-1"))

    ctx = _AuthContext(organization_id="platform")
    assert _visible(ctx, user) == {mine, theirs}


def test_org_admin_sees_only_children_their_org_supervises(user, user2, platform):
    ours = _submission(user2, _child("child-ours", ORG))
    theirs = _submission(user2, _child("child-theirs", OTHER_ORG))

    ctx = _AuthContext(ORG, {Permission.SUBMISSION_READ.value})
    visible = _visible(ctx, user)

    assert ours in visible
    assert theirs not in visible


def test_org_admin_does_not_see_adult_self_submissions(user, user2, platform):
    adult = _submission(user2)

    ctx = _AuthContext(ORG, {Permission.SUBMISSION_READ.value})
    assert adult not in _visible(ctx, user)


def test_org_admin_sees_submissions_predating_the_relation(user, user2, platform):
    """No date bound: approving the relation opens the whole history."""
    child = Child.objects.create(id="child-late", name="child-late")
    old = _submission(user2, child)
    ChildGuardian.objects.create(
        id="rel-late",
        child=child,
        user_id="staff-1",
        role="supervisor",
        status="active",
        organization_id=ORG,
    )

    ctx = _AuthContext(ORG, {Permission.SUBMISSION_READ.value})
    assert old in _visible(ctx, user)


def test_revoked_relation_removes_access(user, user2, platform):
    submission = _submission(user2, _child("child-revoked", ORG, status="ended"))

    ctx = _AuthContext(ORG, {Permission.SUBMISSION_READ.value})
    assert submission not in _visible(ctx, user)


def test_guardian_relation_does_not_put_a_child_in_an_org_list(user, user2, platform):
    """Only the supervisor relation links an organization to a child."""
    submission = _submission(user2, _child("child-guardian", ORG, role="guardian"))

    ctx = _AuthContext(ORG, {Permission.SUBMISSION_READ.value})
    assert submission not in _visible(ctx, user)


def test_caller_always_reads_their_own(user, user2, platform):
    own_adult = _submission(user)
    own_child = _submission(user, _child("child-own", OTHER_ORG))
    someone_else = _submission(user2)

    ctx = _AuthContext(ORG, {Permission.SUBMISSION_READ.value})
    visible = _visible(ctx, user)

    assert {own_adult, own_child} <= visible
    assert someone_else not in visible


def test_plain_user_reads_only_their_own(user, user2, platform):
    mine = _submission(user)
    theirs = _submission(user2, _child("child-plain", ORG))

    ctx = _AuthContext(ORG)
    assert _visible(ctx, user) == {mine}


def test_missing_auth_context_falls_back_to_own(user, user2, platform):
    mine = _submission(user)
    _submission(user2, _child("child-anon", ORG))

    assert _visible(None, user) == {mine}
