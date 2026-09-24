from unittest.mock import Mock

import pytest

from app.permissions import check_permission
from pkg_auth.authorization import MissingPermission


def _info_with_auth(require_should_raise: bool):
    info = Mock()
    info.context.auth_context = Mock()
    if require_should_raise:
        info.context.auth_context.require.side_effect = MissingPermission("nope")
    return info


def test_check_permission_enforces_regardless_of_platform_context():
    """CAP-5: platform-org membership no longer substitutes for a key.

    This gate used to return early on `is_platform_context`, so any member of
    the platform org passed every mutation whatever their role held — which
    made the permission catalog meaningless for platform staff. Platform scope
    is a row-axis concession and lives at `ensure_in_org`; here a platform
    caller is asked for the key like anyone else.

    There used to be two tests either side of that branch, and they are one
    test now because the branch is gone: `app.permissions` no longer imports
    `is_platform_context`, so a platform caller is not a distinguishable case
    at this gate and there is nothing left to patch to construct one.
    """

    @check_permission("survey", "create")
    def view(self, info, **kw):
        return "ok"

    info = _info_with_auth(require_should_raise=True)
    with pytest.raises(PermissionError):
        view(None, info)
    info.context.auth_context.require.assert_called_once_with("surveys:create")


def test_check_permission_passes_through_when_perm_granted():
    @check_permission("assessment", "delete")
    def view(self, info, **kw):
        return "deleted"

    info = _info_with_auth(require_should_raise=False)
    assert view(None, info) == "deleted"
    info.context.auth_context.require.assert_called_once_with("assessments:delete")


def test_check_permission_raises_without_auth_context():
    @check_permission("survey", "read")
    def view(self, info, **kw):
        return "ok"

    info = Mock()
    info.context.auth_context = None
    info.context.identity = None
    with pytest.raises(PermissionError, match="Authentication required"):
        view(None, info)


def test_check_permission_raises_without_org_header():
    @check_permission("survey", "read")
    def view(self, info, **kw):
        return "ok"

    info = Mock()
    info.context.auth_context = None
    info.context.identity = Mock()  # JWT present, but no org context
    with pytest.raises(PermissionError, match="Missing X-Organization-Id"):
        view(None, info)


def test_get_permission_for_kind_names_the_bad_type():
    """A stray `survey_type` used to surface to the client as the message
    `'smart_form'` — a bare KeyError arg, with nothing saying what it was."""
    from app.permissions import get_permission_for_kind

    with pytest.raises(ValueError, match="No permission mapping.*'smart_form'"):
        get_permission_for_kind("smart_form", "delete")


def test_get_permission_for_kind_still_maps_valid_types():
    from app.permissions import Permission, get_permission_for_kind

    assert get_permission_for_kind("form", "delete") is Permission.FORM_DELETE
