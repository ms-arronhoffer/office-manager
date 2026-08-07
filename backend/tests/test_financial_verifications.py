"""PostgreSQL API coverage for consent-gated applicant financial verification."""
from datetime import timedelta
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import select

from app.models.financial_verification import ApplicantFinancialVerification
from app.models.leasing_funnel import RentalApplication
from app.models.organization import Organization
from app.models.user import User
from app.services import financial_verification_service as svc
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio
BASE = "/api/v1/leasing-funnel"


async def _org_user(db, user: User, suffix: str = "a") -> Organization:
    org = Organization(name=f"Tenant {suffix}", slug=f"financial-{suffix}-{uuid.uuid4().hex[:6]}", plan="pro")
    db.add(org)
    await db.flush()
    user.organization_id = org.id
    await db.commit()
    return org


async def _application(db, org: Organization, *, email: str = "applicant@example.com") -> RentalApplication:
    row = RentalApplication(
        organization_id=org.id, applicant_first_name="Jamie", applicant_last_name="Applicant",
        applicant_email=email, applicant_phone="5552223333", status="submitted",
    )
    db.add(row)
    await db.commit()
    return row


async def _verification(db, org, application, raw="secret-token", **values):
    row = ApplicantFinancialVerification(
        organization_id=org.id, application_id=application.id,
        invitation_token_hash=svc.hash_invitation_token(raw),
        expires_at=svc.now() + timedelta(days=7), sent_at=svc.now(), **values,
    )
    db.add(row)
    await db.commit()
    return row


async def test_staff_scoping_and_editor_authorization(client, db_session, admin_user, editor_user, viewer_user):
    org_a = await _org_user(db_session, admin_user, "a")
    editor_user.organization_id = org_a.id
    viewer_user.organization_id = org_a.id
    app_a = await _application(db_session, org_a)
    row = await _verification(db_session, org_a, app_a)

    listed = await client.get(f"{BASE}/applications/{app_a.id}/financial-verifications", headers=auth_headers(editor_user))
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == str(row.id)

    forbidden = await client.post(f"{BASE}/financial-verifications/{row.id}/cancel", headers=auth_headers(viewer_user))
    assert forbidden.status_code == 403

    org_b = Organization(name="Tenant B", slug=f"financial-b-{uuid.uuid4().hex[:6]}", plan="pro")
    db_session.add(org_b)
    await db_session.flush()
    editor_user.organization_id = org_b.id
    await db_session.commit()
    foreign = await client.get(f"{BASE}/applications/{app_a.id}/financial-verifications", headers=auth_headers(editor_user))
    assert foreign.status_code == 404


async def test_staff_create_returns_no_raw_token_and_stores_hash(client, db_session, admin_user, monkeypatch):
    org = await _org_user(db_session, admin_user)
    application = await _application(db_session, org)
    config = SimpleNamespace(is_enabled=True, client_id="client", secret="secret", applicant_verification_enabled=True)
    async def resolved(*args): return config
    monkeypatch.setattr("app.routers.financial_verifications.org_settings.resolve", resolved)
    monkeypatch.setattr("app.routers.financial_verifications._queue_email", lambda *args: None)
    response = await client.post(
        f"{BASE}/applications/{application.id}/financial-verifications",
        headers=auth_headers(admin_user),
    )
    assert response.status_code == 201
    assert "token" not in response.text.casefold()
    row = (await db_session.execute(select(ApplicantFinancialVerification))).scalar_one()
    assert len(row.invitation_token_hash) == 64
    assert row.invitation_token_hash not in response.text


async def test_public_session_requires_consent_and_handles_expiry_decline(client, db_session, admin_user):
    org = await _org_user(db_session, admin_user)
    application = await _application(db_session, org)
    await _verification(db_session, org, application, raw="active-token")

    await client.post(f"{BASE}/financial-verifications/exchange-session", json={"token": "active-token"})
    blocked = await client.post(f"{BASE}/financial-verification-session/exchange", json={"public_token": "public"})
    assert blocked.status_code == 409
    declined = await client.post(f"{BASE}/financial-verification-session/decline")
    assert declined.status_code == 200
    assert declined.json()["status"] == "declined"

    expired = await _verification(db_session, org, application, raw="expired-token")
    expired.expires_at = svc.now() - timedelta(seconds=1)
    await db_session.commit()
    response = await client.post(f"{BASE}/financial-verifications/exchange-session", json={"token": "expired-token"})
    assert response.status_code == 410


async def test_consent_creates_exact_product_link_token(client, db_session, admin_user, monkeypatch):
    org = await _org_user(db_session, admin_user)
    application = await _application(db_session, org)
    row = await _verification(db_session, org, application, raw="consent-token")
    config = SimpleNamespace(is_enabled=True, client_id="client", secret="secret", applicant_verification_enabled=True,
        webhook_url="https://example.test/webhook", api_base_url="https://sandbox.plaid.com", timeout_seconds=10,
        country_codes=("US",), redirect_uri="")

    async def resolved(*args): return config
    captured = {}
    async def link(self, **kwargs):
        captured.update(kwargs)
        return {"link_token": "link-token"}
    monkeypatch.setattr("app.routers.financial_verifications.org_settings.resolve", resolved)
    monkeypatch.setattr("app.routers.financial_verifications.PlaidClient.create_link_token", link)

    await client.post(f"{BASE}/financial-verifications/exchange-session", json={"token": "consent-token"})
    response = await client.post(f"{BASE}/financial-verification-session/consent", json={"accepted": True})
    assert response.status_code == 200
    assert captured["products"] == ["identity", "auth", "transactions"]
    await db_session.refresh(row)
    assert row.consented_at is not None
    assert row.consent_text == svc.CONSENT_TEXT


async def test_exchange_encrypts_then_discards_token_and_retains_minimized_summary(client, db_session, admin_user, monkeypatch):
    org = await _org_user(db_session, admin_user)
    application = await _application(db_session, org)
    row = await _verification(db_session, org, application, raw="exchange-token", status="linking", consented_at=svc.now())
    config = SimpleNamespace(is_enabled=True, client_id="client", secret="secret", applicant_verification_enabled=True,
        webhook_url="", api_base_url="https://sandbox.plaid.com", timeout_seconds=10,
        country_codes=("US",), redirect_uri="")
    async def resolved(*args): return config
    monkeypatch.setattr("app.routers.financial_verifications.org_settings.resolve", resolved)
    monkeypatch.setattr("app.routers.financial_verifications.PlaidClient.exchange_public_token", lambda self, token: _async({"access_token": "access-secret", "item_id": "item-1"}))
    monkeypatch.setattr("app.routers.financial_verifications.PlaidClient.get_identity", lambda self, token: _async({"accounts": [{"owners": [{"names": ["Jamie Applicant"], "emails": [{"data": "applicant@example.com"}], "phone_numbers": []}]}]}))
    monkeypatch.setattr("app.routers.financial_verifications.PlaidClient.get_auth", lambda self, token: _async({"accounts": [{"account_id": "a1"}], "numbers": {"ach": [{"account_id": "a1", "account": "123", "routing": "456"}]}}))
    monkeypatch.setattr("app.routers.financial_verifications.PlaidClient.get_balances", lambda self, token: _async({"accounts": [{"account_id": "a1", "mask": "9999", "balances": {"available": 1000, "current": 1100}}]}))
    monkeypatch.setattr("app.routers.financial_verifications.PlaidClient.get_transactions", lambda self, token, **kwargs: _async({"transactions": [{"date": "2026-07-01", "amount": -3000, "name": "Payroll", "category": ["Income"]}], "total_transactions": 1}))
    monkeypatch.setattr("app.routers.financial_verifications.PlaidClient.remove_item", lambda self, token: _async({"removed": True}))

    await client.post(f"{BASE}/financial-verifications/exchange-session", json={"token": "exchange-token"})
    response = await client.post(f"{BASE}/financial-verification-session/exchange", json={"public_token": "public", "institution_name": "Test Bank"})
    assert response.status_code == 200
    await db_session.refresh(row)
    assert row.status == "completed"
    assert row.access_token_encrypted is None
    assert row.disconnected_at is not None
    serialized = str(row.summary_json)
    assert all(value not in serialized for value in ["123", "456", "9999", "Payroll", "applicant@example.com"])


async def test_resend_rotates_hash_and_cancel_revokes(client, db_session, admin_user):
    org = await _org_user(db_session, admin_user)
    application = await _application(db_session, org)
    row = await _verification(db_session, org, application, raw="old-token")
    old_hash = row.invitation_token_hash
    resent = await client.post(f"{BASE}/financial-verifications/{row.id}/resend", headers=auth_headers(admin_user))
    assert resent.status_code == 200
    await db_session.refresh(row)
    assert row.invitation_token_hash != old_hash
    cancelled = await client.post(f"{BASE}/financial-verifications/{row.id}/cancel", headers=auth_headers(admin_user))
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "revoked"


async def test_webhook_maps_item_revokes_and_deduplicates(client, db_session, admin_user, monkeypatch):
    from app.models.financial_verification import FinancialVerificationWebhookEvent

    org = await _org_user(db_session, admin_user)
    application = await _application(db_session, org)
    row = await _verification(db_session, org, application, status="processing", item_id="item-webhook")
    config = SimpleNamespace(api_base_url="https://sandbox.plaid.com", timeout_seconds=10)
    async def resolved(*args): return config
    async def verified(body, header, plaid_client):
        assert header == "signed-jwt"
        return {"item_id": "item-webhook", "webhook_type": "ITEM", "webhook_code": "USER_PERMISSION_REVOKED"}
    monkeypatch.setattr("app.routers.financial_verifications.org_settings.resolve", resolved)
    monkeypatch.setattr("app.routers.financial_verifications.svc.verify_webhook_jwt", verified)
    payload = {"item_id": "item-webhook", "webhook_type": "ITEM", "webhook_code": "USER_PERMISSION_REVOKED"}
    first = await client.post(f"{BASE}/plaid/webhook", json=payload, headers={"X-Plaid-Verification": "signed-jwt"})
    second = await client.post(f"{BASE}/plaid/webhook", json=payload, headers={"X-Plaid-Verification": "signed-jwt"})
    assert first.status_code == second.status_code == 204
    await db_session.refresh(row)
    assert row.status == "revoked"
    events = (await db_session.execute(select(FinancialVerificationWebhookEvent))).scalars().all()
    assert len(events) == 1


async def _async(value):
    return value