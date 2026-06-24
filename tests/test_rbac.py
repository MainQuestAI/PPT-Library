"""Tests for RBAC permissions (v1.9-B)."""

from __future__ import annotations

import pytest

from ppt_lib.rbac import (
    ROLE_PERMISSIONS,
    Permission,
    PermissionDeniedError,
    Role,
    UserContext,
    check_access,
    get_effective_permissions,
    list_roles,
)


class TestRole:
    def test_roles_defined(self):
        assert Role.VIEWER == "viewer"
        assert Role.EDITOR == "editor"
        assert Role.ADMIN == "admin"
        assert Role.OWNER == "owner"

    def test_all_roles_have_permissions(self):
        for role in Role:
            assert role in ROLE_PERMISSIONS
            assert len(ROLE_PERMISSIONS[role]) > 0


class TestPermission:
    def test_permissions_defined(self):
        assert Permission.SEARCH == "search"
        assert Permission.MANAGE_USERS == "manage_users"
        assert Permission.DELETE_ASSETS == "delete_assets"


class TestUserContext:
    def test_viewer_permissions(self):
        user = UserContext("u1", Role.VIEWER)
        assert user.has_permission(Permission.SEARCH)
        assert user.has_permission(Permission.VIEW_ASSETS)
        assert not user.has_permission(Permission.INDEX_FILES)
        assert not user.has_permission(Permission.MANAGE_USERS)

    def test_editor_permissions(self):
        user = UserContext("u1", Role.EDITOR)
        assert user.has_permission(Permission.SEARCH)
        assert user.has_permission(Permission.INDEX_FILES)
        assert user.has_permission(Permission.EDIT_CLASSIFICATIONS)
        assert not user.has_permission(Permission.MANAGE_USERS)

    def test_admin_permissions(self):
        user = UserContext("u1", Role.ADMIN)
        assert user.has_permission(Permission.MANAGE_USERS)
        assert user.has_permission(Permission.MANAGE_CONFIG)
        assert user.has_permission(Permission.DELETE_ASSETS)
        assert not user.has_permission(Permission.MANAGE_WORKSPACES)

    def test_owner_has_all_permissions(self):
        user = UserContext("u1", Role.OWNER)
        for perm in Permission:
            assert user.has_permission(perm), f"Owner should have {perm}"

    def test_inactive_user_has_no_permissions(self):
        user = UserContext("u1", Role.OWNER, is_active=False)
        assert not user.has_permission(Permission.SEARCH)

    def test_require_permission_success(self):
        user = UserContext("u1", Role.ADMIN)
        user.require_permission(Permission.MANAGE_USERS)  # Should not raise

    def test_require_permission_denied(self):
        user = UserContext("u1", Role.VIEWER)
        with pytest.raises(PermissionDeniedError):
            user.require_permission(Permission.MANAGE_USERS)

    def test_to_json(self):
        user = UserContext("u1", Role.EDITOR, workspace_id="ws1")
        j = user.to_json()
        assert j["user_id"] == "u1"
        assert j["role"] == "editor"
        assert j["workspace_id"] == "ws1"
        assert isinstance(j["permissions"], list)
        assert "search" in j["permissions"]


class TestCheckAccess:
    def test_allowed(self):
        user = UserContext("u1", Role.EDITOR)
        assert check_access(user, Permission.SEARCH) is True

    def test_denied(self):
        user = UserContext("u1", Role.VIEWER)
        assert check_access(user, Permission.INDEX_FILES) is False

    def test_inactive_denied(self):
        user = UserContext("u1", Role.OWNER, is_active=False)
        assert check_access(user, Permission.SEARCH) is False

    def test_workspace_isolation(self):
        user = UserContext("u1", Role.EDITOR, workspace_id="ws1")
        assert check_access(user, Permission.SEARCH, workspace_id="ws1") is True
        assert check_access(user, Permission.SEARCH, workspace_id="ws2") is False


class TestHelperFunctions:
    def test_get_effective_permissions(self):
        perms = get_effective_permissions(Role.VIEWER)
        assert len(perms) > 0
        assert all(isinstance(p, Permission) for p in perms)

    def test_list_roles(self):
        roles = list_roles()
        assert len(roles) == 4
        role_names = {r["role"] for r in roles}
        assert "viewer" in role_names
        assert "owner" in role_names

    def test_role_hierarchy(self):
        viewer_perms = len(ROLE_PERMISSIONS[Role.VIEWER])
        editor_perms = len(ROLE_PERMISSIONS[Role.EDITOR])
        admin_perms = len(ROLE_PERMISSIONS[Role.ADMIN])
        owner_perms = len(ROLE_PERMISSIONS[Role.OWNER])
        assert viewer_perms < editor_perms < admin_perms <= owner_perms
