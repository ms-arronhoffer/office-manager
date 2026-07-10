import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import select

from app.auth.password import hash_password
from app.models.organization import Organization
from app.models.user import User
from tests.conftest import ADMIN_PASSWORD, auth_headers


@pytest.mark.asyncio
async def test_login_success(client, admin_user):
    resp = await client.post("/api/v1/auth/login", json={
        "email": "admin@test.com",
        "password": ADMIN_PASSWORD,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_invalid_password(client, admin_user):
    resp = await client.post("/api/v1/auth/login", json={
        "email": "admin@test.com",
        "password": "wrong",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_user(client):
    resp = await client.post("/api/v1/auth/login", json={
        "email": "nobody@test.com",
        "password": "whatever",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_lockout_after_repeated_failures(client, admin_user):
    """The auth_lockouts table must exist (built by create_all) so the login
    rate-limiter works; repeated failures eventually trigger a 429 lockout."""
    for _ in range(5):
        resp = await client.post("/api/v1/auth/login", json={
            "email": "admin@test.com",
            "password": "wrong",
        })
        assert resp.status_code == 401
    # The 6th attempt is locked out, even with the correct password.
    resp = await client.post("/api/v1/auth/login", json={
        "email": "admin@test.com",
        "password": ADMIN_PASSWORD,
    })
    assert resp.status_code == 429


@pytest.mark.asyncio
async def test_get_me(client, admin_user):
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(admin_user))
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "admin@test.com"
    assert data["role"] == "admin"
    assert data["email_verified"] is False


@pytest.mark.asyncio
async def test_forgot_password_issues_token_for_internal_user(client, admin_user, db_session):
    resp = await client.post("/api/v1/auth/forgot-password", json={"email": admin_user.email})
    assert resp.status_code == 204, resp.text

    await db_session.refresh(admin_user)
    assert admin_user.password_reset_token
    assert admin_user.password_reset_expires_at is not None


@pytest.mark.asyncio
async def test_reset_password_rejects_weak_new_password(client, admin_user, db_session):
    admin_user.password_reset_token = "reset-token"
    admin_user.password_reset_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": "reset-token", "new_password": "password123"},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_register_issues_verification_token_and_verify_email(client, db_session):
    org = Organization(name="Acme", slug="acme", plan="starter", is_active=True)
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)

    admin = User(
        email="owner@test.com",
        display_name="Owner",
        password_hash=hash_password("OwnerPass123!"),
        auth_provider="internal",
        role="admin",
        is_active=True,
        organization_id=org.id,
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)

    resp = await client.post(
        "/api/v1/auth/register",
        headers=auth_headers(admin),
        json={
            "email": "new.user@test.com",
            "display_name": "New User",
            "password": "StrongPass123!",
            "role": "viewer",
        },
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["email_verified"] is False

    created_user = (
        await db_session.execute(select(User).where(User.email == "new.user@test.com"))
    ).scalar_one()
    assert created_user.email_verification_token

    verify_resp = await client.post(
        "/api/v1/auth/verify-email",
        json={"token": created_user.email_verification_token},
    )
    assert verify_resp.status_code == 204, verify_resp.text

    await db_session.refresh(created_user)
    assert created_user.email_verified is True
    assert created_user.email_verification_token is None


@pytest.mark.asyncio
async def test_user_invite_creates_reset_token_without_accepting_password(client, db_session):
    org = Organization(name="Invite Org", slug="invite-org", plan="starter", is_active=True)
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)

    admin = User(
        email="invite-admin@test.com",
        display_name="Invite Admin",
        password_hash=hash_password("InviteAdmin123!"),
        auth_provider="internal",
        role="admin",
        is_active=True,
        organization_id=org.id,
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)

    resp = await client.post(
        "/api/v1/users",
        headers=auth_headers(admin),
        json={
            "email": "invitee@test.com",
            "display_name": "Invitee",
            "role": "editor",
        },
    )
    assert resp.status_code == 201, resp.text
    assert "password" not in resp.json()

    invited_user = (
        await db_session.execute(select(User).where(User.email == "invitee@test.com"))
    ).scalar_one()
    assert invited_user.password_reset_token
    assert invited_user.password_hash
