"""
Role-Based Access Control (RBAC) — 5 roles with 20 granular permissions.

Reference: ImplementationPlan.md M1.3 (Security), PRD Section 14 (Admin).
"""
from __future__ import annotations

from enum import Enum
from functools import wraps
from typing import Any

from fastapi import HTTPException, Request, status


class Role(str, Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    TRADER = "trader"
    VIEWER = "viewer"
    CUSTOM = "custom"


class Permission(str, Enum):
    AGENTS_CREATE = "agents:create"
    AGENTS_READ = "agents:read"
    AGENTS_UPDATE = "agents:update"
    AGENTS_DELETE = "agents:delete"
    AGENTS_APPROVE = "agents:approve"
    AGENTS_PROMOTE = "agents:promote"
    TRADES_READ = "trades:read"
    TRADES_EXECUTE = "trades:execute"
    POSITIONS_READ = "positions:read"
    POSITIONS_CLOSE = "positions:close"
    CONNECTORS_MANAGE = "connectors:manage"
    SKILLS_MANAGE = "skills:manage"
    INSTANCES_MANAGE = "instances:manage"
    BACKTESTS_RUN = "backtests:run"
    TASKS_MANAGE = "tasks:manage"
    AUTOMATIONS_MANAGE = "automations:manage"
    ADMIN_USERS = "admin:users"
    ADMIN_API_KEYS = "admin:api_keys"
    ADMIN_AUDIT = "admin:audit"
    SETTINGS_MANAGE = "settings:manage"


ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.ADMIN: set(Permission),
    Role.MANAGER: {
        Permission.AGENTS_CREATE, Permission.AGENTS_READ, Permission.AGENTS_UPDATE,
        Permission.AGENTS_APPROVE, Permission.AGENTS_PROMOTE,
        Permission.TRADES_READ, Permission.TRADES_EXECUTE,
        Permission.POSITIONS_READ, Permission.POSITIONS_CLOSE,
        Permission.CONNECTORS_MANAGE, Permission.SKILLS_MANAGE,
        Permission.INSTANCES_MANAGE, Permission.BACKTESTS_RUN,
        Permission.TASKS_MANAGE, Permission.AUTOMATIONS_MANAGE,
        Permission.SETTINGS_MANAGE,
    },
    Role.TRADER: {
        Permission.AGENTS_READ, Permission.AGENTS_CREATE,
        Permission.TRADES_READ, Permission.TRADES_EXECUTE,
        Permission.POSITIONS_READ, Permission.POSITIONS_CLOSE,
        Permission.BACKTESTS_RUN, Permission.TASKS_MANAGE,
    },
    Role.VIEWER: {
        Permission.AGENTS_READ, Permission.TRADES_READ,
        Permission.POSITIONS_READ,
    },
    Role.CUSTOM: set(),
}


def get_permissions_for_role(role: str, custom_permissions: list[str] | None = None) -> set[str]:
    """Resolve effective permissions for a role, merging custom overrides."""
    try:
        role_enum = Role(role)
    except ValueError:
        role_enum = Role.VIEWER
    base = {p.value for p in ROLE_PERMISSIONS.get(role_enum, set())}
    if role_enum == Role.CUSTOM and custom_permissions:
        base.update(custom_permissions)
    return base


def check_permission(request: Request, permission: Permission) -> bool:
    """Check if the current request has a specific permission."""
    if getattr(request.state, "is_admin", False):
        return True
    role = getattr(request.state, "role", "viewer")
    custom = getattr(request.state, "permissions", [])
    effective = get_permissions_for_role(role, custom)
    return permission.value in effective


def require_permission(permission: Permission):
    """FastAPI dependency that enforces a permission check."""
    def dependency(request: Request):
        if not check_permission(request, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {permission.value}",
            )
    return dependency


def require_role(*roles: Role):
    """FastAPI dependency that enforces role membership."""
    def dependency(request: Request):
        user_role = getattr(request.state, "role", None)
        if user_role not in {r.value for r in roles}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Required role: {', '.join(r.value for r in roles)}",
            )
    return dependency
