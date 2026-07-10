from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_role import AdminRoleAssignment, CONSOLE_ROLES
from app.models.user import User


DEFAULT_SUPER_ADMIN_ROLE = "super_admin"
DEFAULT_SUPPORT_ROLE = "support"
DEFAULT_FINANCE_ROLE = "finance"


async def resolve_console_role(db: AsyncSession, user: User) -> str | None:
    assignment = (
        await db.execute(
            select(AdminRoleAssignment).where(AdminRoleAssignment.user_id == user.id)
        )
    ).scalar_one_or_none()
    if assignment and assignment.console_role in CONSOLE_ROLES:
        return assignment.console_role
    if user.is_super_admin:
        return DEFAULT_SUPER_ADMIN_ROLE
    return None


async def require_resolved_console_role(db: AsyncSession, user: User) -> str:
    role = await resolve_console_role(db, user)
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin console access required",
        )
    return role


def can_access_console(role: str | None) -> bool:
    return role in CONSOLE_ROLES
