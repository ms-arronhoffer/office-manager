from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.auth.jwt_handler import decode_access_token
from app.models.user import User
from app.models.organization import Organization

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


def require_super_admin():
    """Require the current user to be a platform super-admin."""
    async def checker(user: User = Depends(get_current_user)):
        if not user.is_super_admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super-admin access required")
        return user
    return checker
