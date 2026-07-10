from datetime import datetime, timedelta, timezone

import pyotp
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.google_oauth import verify_google_token
from app.auth.jwt_handler import create_access_token
from app.auth.password_policy import validate_password_strength
from app.auth.password import hash_password, verify_password
from app.database import get_db
from app.models.user import User
from app.schemas.user import (
    ChangePasswordRequest,
    GoogleAuthRequest,
    LoginRequest,
    RegisterRequest,
    UserResponse,
)
from app.services.email_verification_service import issue_verification_token, send_verification_email
from app.services.password_reset_service import issue_password_reset_token, send_password_reset_email

router = APIRouter()

_MAX_ATTEMPTS = 5
_LOCKOUT_MINUTES = 15
_MFA_CHALLENGE_MINUTES = 15
_BACKUP_CODE_COUNT = 8


# ── Brute-force helpers ───────────────────────────────────────────────────────

async def _check_lockout(db: AsyncSession, email: str) -> None:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        text("SELECT locked_until FROM auth_lockouts WHERE email = :email"),
        {"email": email},
    )
    row = result.fetchone()
    if row and row.locked_until:
        locked = row.locked_until
        if locked.tzinfo is None:
            locked = locked.replace(tzinfo=timezone.utc)
        if locked > now:
            remaining = int((locked - now).total_seconds() / 60) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many failed attempts. Try again in {remaining} minute(s).",
            )


async def _track_failure(db: AsyncSession, email: str) -> None:
    await db.execute(
        text(
            "INSERT INTO auth_lockouts (email, failed_attempts, updated_at) "
            "VALUES (:email, 1, now()) "
            "ON CONFLICT (email) DO UPDATE "
            "SET failed_attempts = auth_lockouts.failed_attempts + 1, updated_at = now()"
        ),
        {"email": email},
    )
    result = await db.execute(
        text("SELECT failed_attempts FROM auth_lockouts WHERE email = :email"),
        {"email": email},
    )
    row = result.fetchone()
    if row and row.failed_attempts >= _MAX_ATTEMPTS:
        locked_until = datetime.now(timezone.utc) + timedelta(minutes=_LOCKOUT_MINUTES)
        await db.execute(
            text(
                "UPDATE auth_lockouts SET locked_until = :locked_until, failed_attempts = 0 "
                "WHERE email = :email"
            ),
            {"email": email, "locked_until": locked_until},
        )
    await db.commit()


async def _clear_lockout(db: AsyncSession, email: str) -> None:
    await db.execute(
        text("DELETE FROM auth_lockouts WHERE email = :email"),
        {"email": email},
    )
    await db.commit()


# ── MFA helpers ───────────────────────────────────────────────────────────────

def _make_jwt(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "role": user.role,
        "org_id": str(user.organization_id) if user.organization_id else None,
        "is_super_admin": user.is_super_admin,
    })


async def _mint_challenge(db: AsyncSession, user: User) -> str:
    """Store a short-lived challenge token on the user row and return it."""
    tok = secrets.token_hex(32)
    user.mfa_challenge_token = tok
    user.mfa_challenge_expires_at = datetime.now(timezone.utc) + timedelta(minutes=_MFA_CHALLENGE_MINUTES)
    await db.commit()
    return tok


async def _pop_challenge(db: AsyncSession, mfa_token: str) -> User:
    """Find the user for a valid (unexpired, matching) challenge token.
    Raises 400 if not found or expired. Does NOT clear the token — caller must clear."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(User).where(
            User.mfa_challenge_token == mfa_token,
            User.mfa_challenge_expires_at > now,
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired MFA token")
    return user


async def _verify_totp_or_backup(db: AsyncSession, user: User, code: str) -> None:
    """Verify a TOTP code or a backup code. Raises 400 on failure.
    Removes a used backup code from the list and commits."""
    code = code.strip()
    # Try TOTP first
    if user.totp_secret and pyotp.TOTP(user.totp_secret).verify(code, valid_window=1):
        return
    # Try backup codes
    if user.totp_backup_codes:
        for stored_hash in user.totp_backup_codes:
            if verify_password(code, stored_hash):
                # Consume this backup code
                remaining = [h for h in user.totp_backup_codes if h != stored_hash]
                user.totp_backup_codes = remaining if remaining else None
                await db.commit()
                return
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid authentication code")


# ── Schemas ───────────────────────────────────────────────────────────────────

class LoginResponse(BaseModel):
    access_token: str | None = None
    token_type: str | None = None
    mfa_required: bool = False
    mfa_setup_required: bool = False
    mfa_token: str | None = None


class MfaChallengeRequest(BaseModel):
    mfa_token: str


class MfaVerifyRequest(BaseModel):
    mfa_token: str
    code: str


class MfaEnableResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    backup_codes: list[str]


class MfaSetupResponse(BaseModel):
    secret: str
    qr_uri: str


class MfaDisableRequest(BaseModel):
    code: str


# ── Auth endpoints ────────────────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    email = payload.email

    await _check_lockout(db, email)

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user or not user.password_hash:
        await _track_failure(db, email)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if not verify_password(payload.password, user.password_hash):
        await _track_failure(db, email)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive")
    # Deliberately do not hard-block unverified email addresses here. The
    # frontend uses ``email_verified`` from /auth/me for a softer rollout that
    # does not break existing auth flows or test fixtures.

    await _clear_lockout(db, email)
    user.last_login_at = datetime.now(timezone.utc)

    # Super-admin without TOTP → force setup
    if user.is_super_admin and not user.totp_enabled:
        tok = await _mint_challenge(db, user)
        return LoginResponse(mfa_setup_required=True, mfa_token=tok)

    # Any user with TOTP enabled → require verify
    if user.totp_enabled:
        tok = await _mint_challenge(db, user)
        return LoginResponse(mfa_required=True, mfa_token=tok)

    await db.commit()
    return LoginResponse(access_token=_make_jwt(user), token_type="bearer")


@router.post("/google", response_model=LoginResponse)
async def google_auth(payload: GoogleAuthRequest, db: AsyncSession = Depends(get_db)):
    google_info = await verify_google_token(payload.token)
    if not google_info:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Google token")

    google_sub = google_info["sub"]
    email = google_info["email"]
    name = google_info["name"]

    result = await db.execute(select(User).where(User.google_sub == google_sub))
    user = result.scalar_one_or_none()

    if not user:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

    if user:
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive")
        if not user.google_sub:
            user.google_sub = google_sub
        user.last_login_at = datetime.now(timezone.utc)
    else:
        user = User(
            email=email,
            display_name=name,
            auth_provider="google",
            google_sub=google_sub,
            role="viewer",
            is_active=True,
            last_login_at=datetime.now(timezone.utc),
        )
        db.add(user)

    await db.commit()
    await db.refresh(user)

    if user.is_super_admin and not user.totp_enabled:
        tok = await _mint_challenge(db, user)
        return LoginResponse(mfa_setup_required=True, mfa_token=tok)
    if user.totp_enabled:
        tok = await _mint_challenge(db, user)
        return LoginResponse(mfa_required=True, mfa_token=tok)

    return LoginResponse(access_token=_make_jwt(user), token_type="bearer")


# ── MFA endpoints ─────────────────────────────────────────────────────────────

@router.post("/mfa/setup", response_model=MfaSetupResponse)
async def mfa_setup(payload: MfaChallengeRequest, db: AsyncSession = Depends(get_db)):
    """Generate a TOTP secret and return QR URI. Call before /mfa/enable."""
    user = await _pop_challenge(db, payload.mfa_token)
    secret = pyotp.random_base32()
    user.totp_secret = secret
    await db.commit()
    qr_uri = pyotp.TOTP(secret).provisioning_uri(user.email, issuer_name="Portfolio Desk")
    return MfaSetupResponse(secret=secret, qr_uri=qr_uri)


@router.post("/mfa/enable", response_model=MfaEnableResponse)
async def mfa_enable(payload: MfaVerifyRequest, db: AsyncSession = Depends(get_db)):
    """Confirm the first TOTP code, enable MFA, return JWT + one-time backup codes."""
    user = await _pop_challenge(db, payload.mfa_token)

    if not user.totp_secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Call /mfa/setup first")

    code = payload.code.strip()
    if not pyotp.TOTP(user.totp_secret).verify(code, valid_window=1):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid authentication code")

    # Generate backup codes (plaintext → return once; store bcrypt hashes)
    plain_codes = [secrets.token_hex(6) for _ in range(_BACKUP_CODE_COUNT)]
    hashed_codes = [hash_password(c) for c in plain_codes]

    user.totp_enabled = True
    user.totp_backup_codes = hashed_codes
    user.mfa_challenge_token = None
    user.mfa_challenge_expires_at = None
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()

    return MfaEnableResponse(
        access_token=_make_jwt(user),
        backup_codes=plain_codes,
    )


@router.post("/mfa/verify", response_model=LoginResponse)
async def mfa_verify(payload: MfaVerifyRequest, db: AsyncSession = Depends(get_db)):
    """Verify a TOTP code (or backup code) and issue a JWT."""
    user = await _pop_challenge(db, payload.mfa_token)
    await _verify_totp_or_backup(db, user, payload.code)
    user.mfa_challenge_token = None
    user.mfa_challenge_expires_at = None
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    return LoginResponse(access_token=_make_jwt(user), token_type="bearer")


@router.post("/mfa/disable", status_code=status.HTTP_204_NO_CONTENT)
async def mfa_disable(
    payload: MfaDisableRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Disable TOTP for the authenticated user. Requires a valid TOTP or backup code."""
    await _verify_totp_or_backup(db, current_user, payload.code)
    current_user.totp_enabled = False
    current_user.totp_secret = None
    current_user.totp_backup_codes = None
    await db.commit()


# ── Authenticated endpoints ───────────────────────────────────────────────────

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can register internal accounts")

    result = await db.execute(select(User).where(User.email == payload.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with that email already exists")

    new_user = User(
        email=payload.email,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
        auth_provider="internal",
        role=payload.role,
        is_active=True,
        organization_id=current_user.organization_id,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    verification_token = await issue_verification_token(new_user, db)
    send_verification_email(new_user, verification_token, background_tasks)
    return new_user


@router.post("/refresh", response_model=LoginResponse)
async def refresh_token(current_user: User = Depends(get_current_user)):
    return LoginResponse(access_token=_make_jwt(current_user), token_type="bearer")


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.auth_provider != "internal":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password change is only available for internal accounts")
    if not current_user.password_hash or not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")
    current_user.password_hash = hash_password(payload.new_password)
    await db.commit()


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        return validate_password_strength(value)


class VerifyEmailRequest(BaseModel):
    token: str

@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
async def forgot_password(
    payload: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(User.email == payload.email, User.auth_provider == "internal")
    )
    user = result.scalar_one_or_none()

    if user and user.is_active:
        token = await issue_password_reset_token(user, db)
        send_password_reset_email(user, token, background_tasks)


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(payload: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    if not payload.token or not payload.new_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token and new password are required")

    result = await db.execute(select(User).where(User.password_reset_token == payload.token))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token")

    expires = user.password_reset_expires_at
    if expires is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token")
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token")

    user.password_hash = hash_password(payload.new_password)
    user.password_reset_token = None
    user.password_reset_expires_at = None
    await db.commit()


@router.post("/verify-email", status_code=status.HTTP_204_NO_CONTENT)
async def verify_email(payload: VerifyEmailRequest, db: AsyncSession = Depends(get_db)) -> Response:
    result = await db.execute(select(User).where(User.email_verification_token == payload.token))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification token")

    expires = user.email_verification_expires_at
    if expires is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification token")
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification token")

    user.email_verified = True
    user.email_verification_token = None
    user.email_verification_expires_at = None
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/resend-verification", status_code=status.HTTP_204_NO_CONTENT)
async def resend_verification(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    if current_user.email_verified:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    verification_token = await issue_verification_token(current_user, db)
    send_verification_email(current_user, verification_token, background_tasks)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
