"""Tests for organization single sign-on: state single-use/expiry, ID token
issuer + audience + nonce validation, allowed-domain enforcement, cross-org
isolation, and a successful callback issuing a usable application JWT.

Every identity-provider HTTP call is patched out; nothing here touches the
network.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt as jose_jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.organization_sso_config import OrganizationSsoConfig, SsoLoginState
from app.models.user import User
from app.routers import sso as sso_router
from app.services import sso_service
from app.utils import crypto
from tests.conftest import auth_headers

SSO = "/api/v1/sso"

ISSUER = "https://idp.example.com"
CLIENT_ID = "portfolio-desk-client"
CLIENT_SECRET = "super-secret-client-value"
ALLOWED_DOMAIN = "contoso.com"


# ─── Signing key + fake IdP ────────────────────────────────────────────────

_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode()
_PUBLIC_PEM = _private_key.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
).decode()

_DISCOVERY = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/authorize",
    "token_endpoint": f"{ISSUER}/token",
    "jwks_uri": f"{ISSUER}/jwks",
}

# python-jose accepts a PEM public key in a JWKS "keys" list entry.
_JWKS = {"keys": [_PUBLIC_PEM]}


def make_id_token(
    *,
    nonce: str,
    email: str = f"alice@{ALLOWED_DOMAIN}",
    issuer: str = ISSUER,
    audience: str = CLIENT_ID,
    email_verified: bool = True,
    expires_in: int = 300,
    sub: str = "idp-user-1",
) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "iss": issuer,
        "aud": audience,
        "sub": sub,
        "email": email,
        "email_verified": email_verified,
        "nonce": nonce,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }
    return jose_jwt.encode(claims, _PRIVATE_PEM, algorithm="RS256")


@pytest.fixture(autouse=True)
def stub_idp(monkeypatch):
    """Replace every outbound IdP call with in-process fakes."""
    sso_service.clear_metadata_cache()

    async def _discover(issuer: str):
        return dict(_DISCOVERY)

    async def _fetch_jwks(jwks_uri: str):
        return dict(_JWKS)

    monkeypatch.setattr(sso_service, "discover", _discover)
    monkeypatch.setattr(sso_service, "fetch_jwks", _fetch_jwks)

    async def _no_exchange(*_args, **_kwargs):
        raise AssertionError("token exchange was not armed by the test")

    monkeypatch.setattr(sso_service, "exchange_code", _no_exchange)
    yield
    sso_service.clear_metadata_cache()


@pytest.fixture
def id_token_factory(monkeypatch):
    """Return a helper that arms the token exchange with a given ID token."""

    def _arm(id_token: str):
        async def _exchange(token_endpoint: str, **kwargs):
            return {"id_token": id_token, "token_type": "Bearer"}

        monkeypatch.setattr(sso_service, "exchange_code", _exchange)

    return _arm


# ─── Fixtures ──────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def enterprise_org(db_session: AsyncSession) -> Organization:
    org = Organization(
        id=uuid.uuid4(),
        name="Contoso",
        slug=f"contoso-{uuid.uuid4().hex[:8]}",
        plan="enterprise",
        is_active=True,
    )
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    return org


@pytest_asyncio.fixture
async def sso_config(db_session: AsyncSession, enterprise_org) -> OrganizationSsoConfig:
    config = OrganizationSsoConfig(
        id=uuid.uuid4(),
        organization_id=enterprise_org.id,
        provider="oidc",
        issuer=ISSUER,
        client_id=CLIENT_ID,
        client_secret_encrypted=crypto.encrypt_secret(CLIENT_SECRET),
        allowed_email_domains=[ALLOWED_DOMAIN],
        enforce_sso=False,
        is_enabled=True,
        default_role="viewer",
    )
    db_session.add(config)
    await db_session.commit()
    await db_session.refresh(config)
    return config


@pytest_asyncio.fixture
async def org_admin(db_session: AsyncSession, admin_user, enterprise_org) -> User:
    admin_user.organization_id = enterprise_org.id
    await db_session.commit()
    return admin_user


async def _start_login(client, org: Organization):
    resp = await client.get(f"{SSO}/{org.slug}/authorize")
    assert resp.status_code in (302, 307)
    return resp


async def _pending_state(db_session: AsyncSession) -> SsoLoginState:
    row = (
        await db_session.execute(
            select(SsoLoginState).where(SsoLoginState.consumed_at.is_(None))
        )
    ).scalars().first()
    assert row is not None
    return row


# ─── Authorize leg ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_authorize_redirects_with_pkce_and_state(client, db_session, enterprise_org, sso_config):
    resp = await _start_login(client, enterprise_org)
    location = resp.headers["location"]
    assert location.startswith(f"{ISSUER}/authorize?")
    assert "code_challenge_method=S256" in location
    assert "response_type=code" in location
    assert "state=" in location
    assert "nonce=" in location
    # The client secret must never appear in a browser-visible URL.
    assert CLIENT_SECRET not in location

    row = await _pending_state(db_session)
    assert row.organization_id == enterprise_org.id
    assert row.code_verifier
    assert row.expires_at is not None


@pytest.mark.asyncio
async def test_authorize_unknown_org_is_404(client):
    resp = await client.get(f"{SSO}/no-such-org/authorize")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_authorize_rejected_when_plan_lacks_sso(client, db_session, enterprise_org, sso_config):
    enterprise_org.plan = "pro"
    await db_session.commit()
    resp = await client.get(f"{SSO}/{enterprise_org.slug}/authorize")
    assert resp.status_code == 404


# ─── State validation ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unknown_state_is_rejected(client):
    resp = await client.get(f"{SSO}/callback", params={"state": "never-issued", "code": "abc"})
    assert resp.status_code == 302
    assert "sso_error=invalid_state" in resp.headers["location"]


@pytest.mark.asyncio
async def test_replayed_state_is_rejected(
    client, db_session, enterprise_org, sso_config, id_token_factory
):
    await _start_login(client, enterprise_org)
    row = await _pending_state(db_session)
    id_token_factory(make_id_token(nonce=row.nonce))

    first = await client.get(f"{SSO}/callback", params={"state": row.state, "code": "code-1"})
    assert "sso_token=" in first.headers["location"]

    second = await client.get(f"{SSO}/callback", params={"state": row.state, "code": "code-1"})
    assert "sso_error=invalid_state" in second.headers["location"]


@pytest.mark.asyncio
async def test_expired_state_is_rejected(
    client, db_session, enterprise_org, sso_config, id_token_factory
):
    await _start_login(client, enterprise_org)
    row = await _pending_state(db_session)
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.commit()
    id_token_factory(make_id_token(nonce=row.nonce))

    resp = await client.get(f"{SSO}/callback", params={"state": row.state, "code": "code-1"})
    assert "sso_error=expired_state" in resp.headers["location"]


@pytest.mark.asyncio
async def test_client_secret_decryption_failure_redirects_to_login(
    client, db_session, enterprise_org, sso_config, monkeypatch
):
    await _start_login(client, enterprise_org)
    row = await _pending_state(db_session)

    def _fail_decryption(_ciphertext: str) -> str:
        raise ValueError("Stored secret could not be decrypted.")

    monkeypatch.setattr(sso_router, "decrypt_secret", _fail_decryption)

    resp = await client.get(f"{SSO}/callback", params={"state": row.state, "code": "c"})

    assert resp.status_code == 302
    assert "sso_error=verification_failed" in resp.headers["location"]


# ─── ID token validation ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wrong_audience_is_rejected(
    client, db_session, enterprise_org, sso_config, id_token_factory
):
    await _start_login(client, enterprise_org)
    row = await _pending_state(db_session)
    id_token_factory(make_id_token(nonce=row.nonce, audience="some-other-client"))

    resp = await client.get(f"{SSO}/callback", params={"state": row.state, "code": "c"})
    assert "sso_error=verification_failed" in resp.headers["location"]


@pytest.mark.asyncio
async def test_wrong_issuer_is_rejected(
    client, db_session, enterprise_org, sso_config, id_token_factory
):
    await _start_login(client, enterprise_org)
    row = await _pending_state(db_session)
    id_token_factory(make_id_token(nonce=row.nonce, issuer="https://evil.example.com"))

    resp = await client.get(f"{SSO}/callback", params={"state": row.state, "code": "c"})
    assert "sso_error=verification_failed" in resp.headers["location"]


@pytest.mark.asyncio
async def test_wrong_nonce_is_rejected(
    client, db_session, enterprise_org, sso_config, id_token_factory
):
    await _start_login(client, enterprise_org)
    row = await _pending_state(db_session)
    id_token_factory(make_id_token(nonce="a-different-nonce"))

    resp = await client.get(f"{SSO}/callback", params={"state": row.state, "code": "c"})
    assert "sso_error=verification_failed" in resp.headers["location"]


@pytest.mark.asyncio
async def test_expired_id_token_is_rejected(
    client, db_session, enterprise_org, sso_config, id_token_factory
):
    await _start_login(client, enterprise_org)
    row = await _pending_state(db_session)
    id_token_factory(make_id_token(nonce=row.nonce, expires_in=-60))

    resp = await client.get(f"{SSO}/callback", params={"state": row.state, "code": "c"})
    assert "sso_error=verification_failed" in resp.headers["location"]


def test_unverified_email_claim_is_rejected():
    with pytest.raises(sso_service.SsoError):
        sso_service.extract_verified_email(
            {"email": f"alice@{ALLOWED_DOMAIN}", "email_verified": False}
        )


# ─── Domain + tenant isolation ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_email_outside_allowed_domains_is_rejected(
    client, db_session, enterprise_org, sso_config, id_token_factory
):
    await _start_login(client, enterprise_org)
    row = await _pending_state(db_session)
    id_token_factory(make_id_token(nonce=row.nonce, email="mallory@attacker.test"))

    resp = await client.get(f"{SSO}/callback", params={"state": row.state, "code": "c"})
    assert "sso_error=verification_failed" in resp.headers["location"]

    users = (
        await db_session.execute(select(User).where(User.email == "mallory@attacker.test"))
    ).scalars().all()
    assert users == []


def test_subdomain_does_not_satisfy_allowed_domain():
    assert sso_service.is_domain_allowed(f"a@{ALLOWED_DOMAIN}", [ALLOWED_DOMAIN]) is True
    assert sso_service.is_domain_allowed(f"a@evil.{ALLOWED_DOMAIN}", [ALLOWED_DOMAIN]) is False
    assert sso_service.is_domain_allowed(f"a@{ALLOWED_DOMAIN}", []) is False


@pytest.mark.asyncio
async def test_login_cannot_cross_into_another_organization(
    client, db_session, enterprise_org, sso_config, id_token_factory
):
    other_org = Organization(
        id=uuid.uuid4(), name="Other", slug=f"other-{uuid.uuid4().hex[:8]}", plan="enterprise"
    )
    db_session.add(other_org)
    await db_session.flush()
    existing = User(
        email=f"alice@{ALLOWED_DOMAIN}",
        display_name="Alice Elsewhere",
        organization_id=other_org.id,
        auth_provider="internal",
        role="admin",
        is_active=True,
    )
    db_session.add(existing)
    await db_session.commit()

    await _start_login(client, enterprise_org)
    row = await _pending_state(db_session)
    id_token_factory(make_id_token(nonce=row.nonce))

    resp = await client.get(f"{SSO}/callback", params={"state": row.state, "code": "c"})
    assert "sso_error=verification_failed" in resp.headers["location"]

    await db_session.refresh(existing)
    assert existing.organization_id == other_org.id


# ─── Successful login ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_successful_callback_issues_working_jwt(
    client, db_session, enterprise_org, sso_config, id_token_factory
):
    await _start_login(client, enterprise_org)
    row = await _pending_state(db_session)
    id_token_factory(make_id_token(nonce=row.nonce))

    resp = await client.get(f"{SSO}/callback", params={"state": row.state, "code": "c"})
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert "#" in location and "sso_token=" in location

    from urllib.parse import parse_qs, urlparse

    token = parse_qs(urlparse(location).fragment)["sso_token"][0]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == f"alice@{ALLOWED_DOMAIN}"

    provisioned = (
        await db_session.execute(select(User).where(User.email == f"alice@{ALLOWED_DOMAIN}"))
    ).scalar_one()
    assert provisioned.organization_id == enterprise_org.id
    assert provisioned.auth_provider == "sso"
    assert provisioned.role == "viewer"
    assert provisioned.email_verified is True


@pytest.mark.asyncio
async def test_second_login_reuses_the_same_account(
    client, db_session, enterprise_org, sso_config, id_token_factory
):
    for _ in range(2):
        await _start_login(client, enterprise_org)
        row = await _pending_state(db_session)
        id_token_factory(make_id_token(nonce=row.nonce))
        resp = await client.get(f"{SSO}/callback", params={"state": row.state, "code": "c"})
        assert "sso_token=" in resp.headers["location"]

    users = (
        await db_session.execute(select(User).where(User.email == f"alice@{ALLOWED_DOMAIN}"))
    ).scalars().all()
    assert len(users) == 1


# ─── Lookup ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lookup_by_email_domain(client, enterprise_org, sso_config):
    resp = await client.get(f"{SSO}/lookup", params={"email": f"bob@{ALLOWED_DOMAIN}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["organization_slug"] == enterprise_org.slug


@pytest.mark.asyncio
async def test_lookup_unknown_domain_reports_disabled(client, sso_config):
    resp = await client.get(f"{SSO}/lookup", params={"email": "bob@nowhere.test"})
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False


# ─── Admin configuration ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_viewer_cannot_read_config(client, db_session, viewer_user, enterprise_org):
    viewer_user.organization_id = enterprise_org.id
    await db_session.commit()
    resp = await client.get(f"{SSO}/config", headers=auth_headers(viewer_user))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_config_requires_sso_entitlement(client, db_session, org_admin, enterprise_org):
    enterprise_org.plan = "pro"
    await db_session.commit()
    resp = await client.get(f"{SSO}/config", headers=auth_headers(org_admin))
    assert resp.status_code == 402


@pytest.mark.asyncio
async def test_save_config_encrypts_secret_and_never_returns_it(
    client, db_session, org_admin, enterprise_org, monkeypatch
):
    from cryptography.fernet import Fernet

    monkeypatch.setattr(crypto.settings, "ENCRYPTION_KEY", Fernet.generate_key().decode())

    resp = await client.put(
        f"{SSO}/config",
        json={
            "issuer": ISSUER,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "allowed_email_domains": [f"  @{ALLOWED_DOMAIN.upper()} "],
            "enforce_sso": False,
            "is_enabled": True,
            "default_role": "viewer",
        },
        headers=auth_headers(org_admin),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True
    assert body["allowed_email_domains"] == [ALLOWED_DOMAIN]
    assert CLIENT_SECRET not in resp.text

    stored = (
        await db_session.execute(
            select(OrganizationSsoConfig).where(
                OrganizationSsoConfig.organization_id == enterprise_org.id
            )
        )
    ).scalar_one()
    assert CLIENT_SECRET not in stored.client_secret_encrypted
    assert crypto.decrypt_secret(stored.client_secret_encrypted) == CLIENT_SECRET


@pytest.mark.asyncio
async def test_save_config_rejects_non_https_issuer(client, org_admin):
    resp = await client.put(
        f"{SSO}/config",
        json={
            "issuer": "http://idp.example.com",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "allowed_email_domains": [ALLOWED_DOMAIN],
        },
        headers=auth_headers(org_admin),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_save_config_requires_a_domain(client, org_admin):
    resp = await client.put(
        f"{SSO}/config",
        json={
            "issuer": ISSUER,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "allowed_email_domains": [],
        },
        headers=auth_headers(org_admin),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_without_secret_keeps_stored_secret(
    client, db_session, org_admin, enterprise_org, sso_config
):
    resp = await client.put(
        f"{SSO}/config",
        json={
            "issuer": ISSUER,
            "client_id": "rotated-client-id",
            "allowed_email_domains": [ALLOWED_DOMAIN],
            "is_enabled": True,
        },
        headers=auth_headers(org_admin),
    )
    assert resp.status_code == 200

    await db_session.refresh(sso_config)
    assert sso_config.client_id == "rotated-client-id"
    assert crypto.decrypt_secret(sso_config.client_secret_encrypted) == CLIENT_SECRET


@pytest.mark.asyncio
async def test_delete_config_removes_it(client, db_session, org_admin, enterprise_org, sso_config):
    resp = await client.delete(f"{SSO}/config", headers=auth_headers(org_admin))
    assert resp.status_code == 204

    remaining = (
        await db_session.execute(
            select(OrganizationSsoConfig).where(
                OrganizationSsoConfig.organization_id == enterprise_org.id
            )
        )
    ).scalars().all()
    assert remaining == []


# ─── enforce_sso blocks password login ─────────────────────────────────────

@pytest.mark.asyncio
async def test_enforce_sso_blocks_password_login(
    client, db_session, org_admin, sso_config
):
    sso_config.enforce_sso = True
    await db_session.commit()

    from tests.conftest import ADMIN_PASSWORD

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": org_admin.email, "password": ADMIN_PASSWORD},
    )
    assert resp.status_code == 403


# ─── Issuer hardening ──────────────────────────────────────────────────────

def test_normalize_issuer_rejects_non_https():
    for bad in ("http://idp.example.com", "ftp://idp.example.com", "", "not-a-url"):
        with pytest.raises(sso_service.SsoError):
            sso_service.normalize_issuer(bad)
    assert sso_service.normalize_issuer("https://idp.example.com/") == "https://idp.example.com"


def test_pkce_challenge_is_s256_of_verifier():
    import base64
    import hashlib

    verifier, challenge = sso_service.generate_pkce()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    assert challenge == expected
    assert len(verifier) >= 43
