from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt_handler import create_access_token
from app.config import settings
from app.models.refresh_session import RefreshSession
from app.models.user import User
from app.services.console_roles import resolve_console_role

ACCESS_COOKIE = "om_access"
REFRESH_COOKIE = "om_refresh"
CSRF_COOKIE = "om_csrf"
_REFRESH_DAYS = 7


def _secure_cookies() -> bool:
    return settings.APP_ENV.lower() in {"production", "prod", "staging"}


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _client_metadata(request: Request) -> tuple[str | None, str | None]:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    ip_address = forwarded or (request.client.host if request.client else None)
    return request.headers.get("user-agent"), ip_address


async def make_access_token(db: AsyncSession, user: User) -> str:
    console_role = await resolve_console_role(db, user)
    return create_access_token({
        "sub": str(user.id),
        "role": user.role,
        "org_id": str(user.organization_id) if user.organization_id else None,
        "is_super_admin": user.is_super_admin,
        "console_role": console_role,
    })


def set_access_cookie(response: Response, access_token: str, *, max_age: int | None = None) -> None:
    secure = _secure_cookies()
    csrf_token = secrets.token_urlsafe(32)
    response.set_cookie(
        ACCESS_COOKIE, access_token, max_age=max_age or settings.JWT_ACCESS_MINUTES * 60,
        secure=secure, httponly=True, samesite="lax", path="/",
    )
    response.set_cookie(
        CSRF_COOKIE, csrf_token, max_age=max_age or _REFRESH_DAYS * 86400,
        secure=secure, httponly=False, samesite="strict", path="/",
    )


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    secure = _secure_cookies()
    set_access_cookie(response, access_token)
    response.set_cookie(
        REFRESH_COOKIE, refresh_token, max_age=_REFRESH_DAYS * 86400,
        secure=secure, httponly=True, samesite="strict", path="/api/v1/auth",
    )


def clear_auth_cookies(response: Response) -> None:
    secure = _secure_cookies()
    response.delete_cookie(ACCESS_COOKIE, path="/", secure=secure, httponly=True, samesite="lax")
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth", secure=secure, httponly=True, samesite="strict")
    response.delete_cookie(CSRF_COOKIE, path="/", secure=secure, httponly=False, samesite="strict")


async def issue_session(
    db: AsyncSession, user: User, request: Request, response: Response,
    *, family_id: uuid.UUID | None = None,
) -> str:
    session_id = uuid.uuid4()
    secret = secrets.token_urlsafe(48)
    raw_token = f"{session_id}.{secret}"
    now = datetime.now(timezone.utc)
    user_agent, ip_address = _client_metadata(request)
    db.add(RefreshSession(
        id=session_id,
        family_id=family_id or uuid.uuid4(),
        user_id=user.id,
        organization_id=user.organization_id,
        token_hash=_hash_token(raw_token),
        created_at=now,
        expires_at=now + timedelta(days=_REFRESH_DAYS),
        user_agent=user_agent,
        ip_address=ip_address,
    ))
    access_token = await make_access_token(db, user)
    set_auth_cookies(response, access_token, raw_token)
    return access_token


async def rotate_session(db: AsyncSession, raw_token: str, request: Request, response: Response) -> tuple[User, str]:
    try:
        session_id = uuid.UUID(raw_token.split(".", 1)[0])
    except (ValueError, IndexError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")

    session = (
        await db.execute(select(RefreshSession).where(RefreshSession.id == session_id).with_for_update())
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if session is None or not secrets.compare_digest(session.token_hash, _hash_token(raw_token)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    if session.revoked_at is not None:
        await db.execute(
            update(RefreshSession)
            .where(RefreshSession.family_id == session.family_id, RefreshSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await db.commit()
        clear_auth_cookies(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session reuse detected")
    if session.expires_at <= now:
        session.revoked_at = now
        await db.commit()
        clear_auth_cookies(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")

    user = (
        await db.execute(select(User).where(User.id == session.user_id, User.is_active.is_(True)))
    ).scalar_one_or_none()
    if user is None:
        session.revoked_at = now
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")

    session.revoked_at = now
    session.last_used_at = now
    new_id = uuid.uuid4()
    new_secret = secrets.token_urlsafe(48)
    new_raw_token = f"{new_id}.{new_secret}"
    user_agent, ip_address = _client_metadata(request)
    db.add(RefreshSession(
        id=new_id,
        family_id=session.family_id,
        user_id=user.id,
        organization_id=user.organization_id,
        token_hash=_hash_token(new_raw_token),
        created_at=now,
        expires_at=now + timedelta(days=_REFRESH_DAYS),
        user_agent=user_agent,
        ip_address=ip_address,
    ))
    session.replaced_by_id = new_id
    access_token = await make_access_token(db, user)
    set_auth_cookies(response, access_token, new_raw_token)
    return user, access_token


async def revoke_all_sessions(db: AsyncSession, user_id: uuid.UUID, *, except_id: uuid.UUID | None = None) -> None:
    statement = update(RefreshSession).where(
        RefreshSession.user_id == user_id,
        RefreshSession.revoked_at.is_(None),
    )
    if except_id is not None:
        statement = statement.where(RefreshSession.id != except_id)
    await db.execute(statement.values(revoked_at=datetime.now(timezone.utc)))