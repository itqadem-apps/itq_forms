from unittest.mock import Mock, patch

import pytest

from app.permissions import check_permission
from pkg_auth.authorization import MissingPermission


def _info_with_auth(require_should_raise: bool):
    info = Mock()
    info.context.auth_context = Mock()
    if require_should_raise:
        info.context.auth_context.require.side_effect = MissingPermission("nope")
    return info


@patch("app.permissions.is_platform_context", return_value=True)
def test_check_permission_bypasses_for_platform_context(_mock):
    @check_permission("survey", "create")
    def view(self, info, **kw):
        return "ok"

    info = _info_with_auth(require_should_raise=True)
    assert view(None, info) == "ok"
    assert info.context.auth_context.require.call_count == 0


@patch("app.permissions.is_platform_context", return_value=False)
def test_check_permission_enforces_for_non_platform_context(_mock):
    @check_permission("survey", "create")
    def view(self, info, **kw):
        return "ok"

    info = _info_with_auth(require_should_raise=True)
    with pytest.raises(PermissionError):
        view(None, info)
    info.context.auth_context.require.assert_called_once_with("surveys:create")


@patch("app.permissions.is_platform_context", return_value=False)
def test_check_permission_passes_through_when_perm_granted(_mock):
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
