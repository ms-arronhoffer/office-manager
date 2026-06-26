"""Tests for the AI-assist API (Google Gemini).

The Gemini client is always mocked — no real API key is exercised. These tests
assert entitlement gating (basic ingestion is open to all tiers; richer AI is
Pro+), graceful degradation when the key is unset, and schema mapping.
"""
import io

import pytest

from app.auth.jwt_handler import create_access_token
from app.auth.password import hash_password
from app.models.organization import Organization
from app.models.user import User
from app.services import ai_service


async def _make_org_user(db_session, plan: str, email: str) -> dict[str, str]:
    org = Organization(name=f"Org {plan}", slug=f"org-{plan}-{email[:3]}", plan=plan)
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    user = User(
        email=email,
        display_name="U",
        password_hash=hash_password("x"),
        auth_provider="internal",
        role="admin",
        is_active=True,
        organization_id=org.id,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return {"Authorization": "Bearer " + token}


def _doc():
    return ("lease.txt", io.BytesIO(b"Lessor: Acme. Commencement 2024-01-01."), "text/plain")


@pytest.mark.asyncio
async def test_status_reports_configuration(client, admin_user, monkeypatch):
    from tests.conftest import auth_headers

    monkeypatch.setattr(ai_service, "is_configured", lambda: False)
    resp = await client.get("/api/v1/ai/status", headers=auth_headers(admin_user))
    assert resp.status_code == 200, resp.text
    assert resp.json()["configured"] is False


@pytest.mark.asyncio
async def test_basic_lease_parse_allowed_on_starter(client, db_session, monkeypatch):
    """Basic lease ingestion must work on every tier (not gated by ai_assist)."""
    headers = await _make_org_user(db_session, "starter", "starter@test.com")

    async def fake_parse(content, mime_type):
        return {"lessor_name": "Acme", "lease_commencement": "2024-01-01"}

    monkeypatch.setattr(ai_service, "parse_lease_document", fake_parse)

    resp = await client.post("/api/v1/ai/leases/parse", headers=headers, files={"file": _doc()})
    assert resp.status_code == 200, resp.text
    assert resp.json()["suggested"]["lessor_name"] == "Acme"


@pytest.mark.asyncio
async def test_basic_lease_parse_degrades_when_unconfigured(client, db_session, monkeypatch):
    headers = await _make_org_user(db_session, "starter", "starter2@test.com")

    async def fake_parse(content, mime_type):
        raise ai_service.AIUnavailableError("AI assist is not configured")

    monkeypatch.setattr(ai_service, "parse_lease_document", fake_parse)

    resp = await client.post("/api/v1/ai/leases/parse", headers=headers, files={"file": _doc()})
    assert resp.status_code == 503, resp.text


@pytest.mark.asyncio
async def test_summary_gated_for_starter(client, db_session):
    headers = await _make_org_user(db_session, "starter", "starter3@test.com")
    resp = await client.post("/api/v1/ai/reports/summary", headers=headers, json={"period": "weekly"})
    assert resp.status_code == 402, resp.text


@pytest.mark.asyncio
async def test_summary_allowed_for_pro(client, db_session, monkeypatch):
    headers = await _make_org_user(db_session, "pro", "pro@test.com")

    async def fake_narrative(period_label, data):
        return f"Briefing for {period_label}."

    monkeypatch.setattr(ai_service, "generate_summary_narrative", fake_narrative)

    resp = await client.post("/api/v1/ai/reports/summary", headers=headers, json={"period": "weekly"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["period"] == "weekly"
    assert "Briefing for" in body["narrative"]
    assert "open_tickets" in body["data"]


@pytest.mark.asyncio
async def test_abstract_suggest_gated_for_starter(client, db_session):
    headers = await _make_org_user(db_session, "starter", "starter4@test.com")
    import uuid

    resp = await client.post(
        f"/api/v1/ai/leases/{uuid.uuid4()}/abstract/suggest",
        headers=headers,
        files={"file": _doc()},
    )
    assert resp.status_code == 402, resp.text
