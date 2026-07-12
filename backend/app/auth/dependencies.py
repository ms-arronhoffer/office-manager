from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.auth.jwt_handler import decode_access_token
from app.models.user import User
from app.models.organization import Organization
from app.services.console_roles import require_resolved_console_role

security = HTTPBearer()


async def _authenticate_api_key(token: str, db: AsyncSession) -> User:
    """Validate an `om_` prefixed API key and return the associated user."""
    from app.models.api_key import ApiKey, hash_api_key  # local import to avoid circular deps

    key_hash = hash_api_key(token)
    result = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True))
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key expired")

    # Update last_used_at (best-effort)
    try:
        api_key.last_used_at = datetime.now(timezone.utc)
        await db.commit()
    except Exception:
        await db.rollback()

    # Fetch the owning user
    user_result = await db.execute(select(User).where(User.id == api_key.user_id, User.is_active.is_(True)))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key owner not found")
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials
    if token.startswith("om_"):
        return await _authenticate_api_key(token, db)
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    if user.organization_id is not None:
        from app.utils.rls import set_session_org  # local import to avoid cycles

        await set_session_org(db, user.organization_id)
    return user


async def get_current_org(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Organization:
    """Return the Organization for the current user. Super-admins without an org raise 400."""
    if user.organization_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User has no organization")
    result = await db.execute(select(Organization).where(Organization.id == user.organization_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    if not org.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization is inactive")
    from app.utils.rls import set_session_org  # local import to avoid cycles

    await set_session_org(db, org.id)
    return org


def require_role(*roles: str):
    """Check that the current user has one of the given roles.
    Super-admins bypass all role checks."""
    async def checker(user: User = Depends(get_current_user)):
        if user.is_super_admin:
            return user
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user
    return checker



def require_console_role(*roles: str):
    """Require that the current user has one of the allowed admin-console roles."""
    async def checker(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        console_role = await require_resolved_console_role(db, user)
        if roles and console_role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient console permissions")
        setattr(user, "console_role", console_role)
        return user
    return checker



def require_super_admin():
    """Require the current user to be a platform super-admin."""
    async def checker(user: User = Depends(get_current_user)):
        if not user.is_super_admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super-admin access required")
        return user
    return checker


async def enforce_org_access(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Block access when the user's organization is suspended or unpaid.

    Super-admins and users without an organization bypass this check. Orgs that
    are inactive, canceled, or past-due beyond the grace period get a 403 with
    an explanatory message. Past-due orgs still within grace are allowed through.
    """
    from app.services import entitlements as ent  # local import avoids cycle

    if user.is_super_admin or user.organization_id is None:
        return user

    result = await db.execute(select(Organization).where(Organization.id == user.organization_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    state = ent.org_access_state(org)
    if ent.is_access_blocked(state):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ent.access_denied_message(state),
        )
    from app.utils.rls import set_session_org  # local import to avoid cycles

    await set_session_org(db, org.id)
    return user


def require_feature(feature: str):
    """Require the current user's organization to be entitled to ``feature``.

    Super-admins and org-less users bypass the check (mirroring
    ``enforce_org_access``, where users without an organization are treated as
    internal/platform accounts). Orgs lacking the feature receive a 402 (payment
    required) with an upgrade message.
    """
    async def checker(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        from app.services import entitlements as ent  # local import avoids cycle

        if user.is_super_admin or user.organization_id is None:
            return user

        result = await db.execute(select(Organization).where(Organization.id == user.organization_id))
        org = result.scalar_one_or_none()
        if not org:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

        if not ent.has_feature(org, feature):
            # Features that are planned but not yet available get a friendlier
            # "coming soon" message instead of a generic upgrade prompt.
            _COMING_SOON = {"sso", "custom_fields"}
            if feature in _COMING_SOON:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=(
                        f"The '{feature}' feature is coming soon. "
                        "Contact support to join the early access list."
                    ),
                )
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"The '{feature}' feature is not included in your {org.plan} plan. "
                       "Upgrade your plan to enable it.",
            )
        return user

    return checker


def require_category(category: str):
    """Require the current user's organization to have ``category`` enabled.

    A *primary category* is a line of business the org runs (see
    ``app.services.categories``). Mirrors ``require_feature`` but gates on the
    org's enabled categories rather than plan entitlements.

    Super-admins and org-less users bypass the check (they are treated as
    internal/platform accounts). Orgs that have the category disabled receive a
    403 with an explanatory message; disabling is non-destructive, so the data
    still exists — the surface is simply turned off.
    """
    async def checker(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        from app.services import categories as cat  # local import avoids cycle

        if user.is_super_admin or user.organization_id is None:
            return user

        result = await db.execute(select(Organization).where(Organization.id == user.organization_id))
        org = result.scalar_one_or_none()
        if not org:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

        if not cat.is_category_enabled(org, category):
            label = cat.CATEGORY_LABELS.get(category, category)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"The '{label}' category is turned off for your organization. "
                    "An administrator can re-enable it in settings."
                ),
            )
        return user

    return checker
