"""Tests for the admin console Stripe integration config and cross-org support
request queue (added alongside audit pagination)."""
import pytest

from app.auth.password import hash_password
from app.models.organization import Organization
from app.models.support_request import SupportRequest
from app.models.user import User
from app.utils.crypto import decrypt_secret
from tests.conftest import auth_headers


async def _super_admin(db):
    sa = User(
        email="rootcfg@test.com", display_name="Root", password_hash=hash_password("pw12345678"),
        auth_provider="internal", role="admin", is_active=True, is_super_admin=True,
    )
    db.add(sa)
    await db.commit()
    await db.refresh(sa)
    return sa


async def _plain_admin(db):
    org = Organization(name="PlainCo", slug="plainco", plan="pro", is_active=True)
    db.add(org)
    await db.commit()
    await db.refresh(org)
    u = User(
        email="plain@test.com", display_name="Plain", password_hash=hash_password("pw12345678"),
        auth_provider="internal", role="admin", is_active=True, organization_id=org.id,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return org, u


# ─── Stripe config ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stripe_config_starts_unconfigured(client, db_session):
    sa = await _super_admin(db_session)
    r = await client.get("/admin/v1/billing/stripe-config", headers=auth_headers(sa))
    assert r.status_code == 200, r.text
    body = r.json()
    # No DB row and no env key in tests → not configured, no hint.
    assert body["secret_key_hint"] is None


@pytest.mark.asyncio
async def test_stripe_config_save_masks_and_encrypts(client, db_session):
    sa = await _super_admin(db_session)
    r = await client.put(
        "/admin/v1/billing/stripe-config", headers=auth_headers(sa),
        json={"secret_key": "sk_test_supersecret123", "webhook_secret": "whsec_abc", "price_id_pro": "price_pro"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["configured"] is True
    assert body["secret_key_from_env"] is False
    # Secret is never returned verbatim, only a masked tail.
    assert "sk_test_supersecret123" not in str(body)
    assert body["secret_key_hint"].endswith("t123")
    assert body["price_id_pro"] == "price_pro"

    # Stored encrypted but decryptable back to the original.
    from app.services.stripe_settings import get_stripe_config
    cfg = await get_stripe_config(db_session)
    assert cfg is not None
    assert cfg.secret_key_encrypted != "sk_test_supersecret123"
    assert decrypt_secret(cfg.secret_key_encrypted) == "sk_test_supersecret123"


@pytest.mark.asyncio
async def test_stripe_config_partial_update_keeps_secret(client, db_session):
    sa = await _super_admin(db_session)
    await client.put(
        "/admin/v1/billing/stripe-config", headers=auth_headers(sa),
        json={"secret_key": "sk_test_keepme"},
    )
    # Update only a non-secret field; secret must survive.
    r = await client.put(
        "/admin/v1/billing/stripe-config", headers=auth_headers(sa),
        json={"price_id_enterprise": "price_ent"},
    )
    assert r.status_code == 200, r.text
    from app.services.stripe_settings import resolve_stripe_secret_key
    assert await resolve_stripe_secret_key(db_session) == "sk_test_keepme"
    assert r.json()["price_id_enterprise"] == "price_ent"


@pytest.mark.asyncio
async def test_stripe_config_disabled_falls_back(client, db_session):
    sa = await _super_admin(db_session)
    await client.put(
        "/admin/v1/billing/stripe-config", headers=auth_headers(sa),
        json={"secret_key": "sk_test_disabled", "is_enabled": False},
    )
    from app.services.stripe_settings import resolve_stripe_secret_key
    # Disabled config → does not surface the stored secret (env empty in tests).
    assert await resolve_stripe_secret_key(db_session) == ""


@pytest.mark.asyncio
async def test_stripe_config_requires_console_role(client, db_session):
    _, plain = await _plain_admin(db_session)
    r = await client.get("/admin/v1/billing/stripe-config", headers=auth_headers(plain))
    assert r.status_code == 403


# ─── Cross-org support requests ───────────────────────────────────────────────

async def _support_setup(db):
    sa = await _super_admin(db)
    org = Organization(name="HelpCo", slug="helpco", plan="pro", is_active=True)
    db.add(org)
    await db.commit()
    await db.refresh(org)
    req = SupportRequest(
        organization_id=org.id, subject="Cannot login", message="It broke", status="open",
        requester_name="Alice", requester_email="alice@help.co",
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)
    return sa, org, req


@pytest.mark.asyncio
async def test_admin_support_requests_list_cross_org(client, db_session):
    sa, org, req = await _support_setup(db_session)
    r = await client.get("/admin/v1/support-requests", headers=auth_headers(sa))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    row = next(x for x in body["items"] if x["id"] == str(req.id))
    assert row["organization_name"] == "HelpCo"
    assert row["subject"] == "Cannot login"


@pytest.mark.asyncio
async def test_admin_support_requests_status_filter(client, db_session):
    sa, org, req = await _support_setup(db_session)
    r = await client.get("/admin/v1/support-requests?status=resolved", headers=auth_headers(sa))
    assert r.status_code == 200
    assert all(x["status"] == "resolved" for x in r.json()["items"])


@pytest.mark.asyncio
async def test_admin_support_request_update_status(client, db_session):
    sa, org, req = await _support_setup(db_session)
    r = await client.patch(
        f"/admin/v1/support-requests/{req.id}", headers=auth_headers(sa),
        json={"status": "resolved"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "resolved"


@pytest.mark.asyncio
async def test_admin_support_request_rejects_bad_status(client, db_session):
    sa, org, req = await _support_setup(db_session)
    r = await client.patch(
        f"/admin/v1/support-requests/{req.id}", headers=auth_headers(sa),
        json={"status": "bogus"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_admin_support_requests_requires_console_role(client, db_session):
    _, plain = await _plain_admin(db_session)
    r = await client.get("/admin/v1/support-requests", headers=auth_headers(plain))
    assert r.status_code == 403
