"""Role-Based Access Control for team mode (v1.9-B).

Defines roles, permissions, and access control for multi-user deployments.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    """User roles in the system."""

    VIEWER = "viewer"
    EDITOR = "editor"
    ADMIN = "admin"
    OWNER = "owner"


class Permission(StrEnum):
    """Granular permissions."""

    # Read
    SEARCH = "search"
    VIEW_ASSETS = "view_assets"
    VIEW_HEALTH = "view_health"
    VIEW_JOBS = "view_jobs"
    VIEW_AUDIT = "view_audit"

    # Write
    INDEX_FILES = "index_files"
    EDIT_CLASSIFICATIONS = "edit_classifications"
    RESOLVE_HEALTH = "resolve_health"
    CANCEL_JOBS = "cancel_jobs"

    # Admin
    MANAGE_USERS = "manage_users"
    MANAGE_CONFIG = "manage_config"
    MANAGE_WORKSPACES = "manage_workspaces"
    EXPORT_DATA = "export_data"
    DELETE_ASSETS = "delete_assets"


# Role -> Permission mapping
ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.VIEWER: {
        Permission.SEARCH,
        Permission.VIEW_ASSETS,
        Permission.VIEW_HEALTH,
        Permission.VIEW_JOBS,
    },
    Role.EDITOR: {
        Permission.SEARCH,
        Permission.VIEW_ASSETS,
        Permission.VIEW_HEALTH,
        Permission.VIEW_JOBS,
        Permission.INDEX_FILES,
        Permission.EDIT_CLASSIFICATIONS,
        Permission.RESOLVE_HEALTH,
        Permission.CANCEL_JOBS,
    },
    Role.ADMIN: {
        Permission.SEARCH,
        Permission.VIEW_ASSETS,
        Permission.VIEW_HEALTH,
        Permission.VIEW_JOBS,
        Permission.VIEW_AUDIT,
        Permission.INDEX_FILES,
        Permission.EDIT_CLASSIFICATIONS,
        Permission.RESOLVE_HEALTH,
        Permission.CANCEL_JOBS,
        Permission.MANAGE_USERS,
        Permission.MANAGE_CONFIG,
        Permission.EXPORT_DATA,
        Permission.DELETE_ASSETS,
    },
    Role.OWNER: set(Permission),  # All permissions
}


@dataclass(frozen=True)
class UserContext:
    """The current user's context for permission checks."""

    user_id: str
    role: Role
    workspace_id: str = "default"
    is_active: bool = True

    def has_permission(self, permission: Permission) -> bool:
        """Check if the user has a specific permission."""
        if not self.is_active:
            return False
        return permission in ROLE_PERMISSIONS.get(self.role, set())

    def require_permission(self, permission: Permission) -> None:
        """Raise if user doesn't have the required permission."""
        if not self.has_permission(permission):
            raise PermissionDeniedError(
                f"User {self.user_id} with role {self.role} "
                f"lacks permission {permission}"
            )

    def to_json(self) -> dict[str, object]:
        return {
            "user_id": self.user_id,
            "role": self.role,
            "workspace_id": self.workspace_id,
            "is_active": self.is_active,
            "permissions": sorted(
                p.value for p in ROLE_PERMISSIONS.get(self.role, set())
            ),
        }


class PermissionDeniedError(Exception):
    """Raised when a user lacks the required permission."""


def check_access(
    user: UserContext,
    permission: Permission,
    *,
    workspace_id: str | None = None,
) -> bool:
    """Check if a user has access to perform an action.

    Optionally checks workspace isolation.
    """
    if not user.is_active:
        return False
    if not user.has_permission(permission):
        return False
    if workspace_id and user.workspace_id != workspace_id:
        return False
    return True


def get_effective_permissions(role: Role) -> list[Permission]:
    """Get all permissions for a role."""
    return sorted(ROLE_PERMISSIONS.get(role, set()), key=lambda p: p.value)


def list_roles() -> list[dict[str, object]]:
    """List all roles with their permissions."""
    return [
        {
            "role": role.value,
            "permissions": sorted(p.value for p in perms),
            "permission_count": len(perms),
        }
        for role, perms in ROLE_PERMISSIONS.items()
    ]
