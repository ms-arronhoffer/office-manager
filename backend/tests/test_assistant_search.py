"""Tests for global search enrichment and the in-app assistant (Item 5)."""
import pytest

from app.auth.jwt_handler import create_access_token
from app.auth.password import hash_password
from app.models.organization import Organization
from app.models.user import User
from app.models.vendor import Vendor
from app.services import ai_service
from tests.conftest import auth_headers


async def _make_org_user(db_session, plan: str, email: str, role: str = "admin") -> dict:
    org = Organization(name=f"Org {plan}", slug=f"org-{plan}-{email[:5]}", plan=plan)
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    user = User(
        email=email, display_name="U", password_hash=hash_password("x"),
        auth_provider="internal", role=role, is_active=True, organization_id=org.id,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return {"Authorization": "Bearer " + create_access_token({"sub": str(user.id), "role": user.role})}


# ── Phase (a)/(b): richer search + deep-link routes ────────────────────────────

@pytest.mark.asyncio
async def test_search_includes_vendors_with_route(client, admin_user, db_session):
    db_session.add(Vendor(company_name="Acme Plumbing Co", contact_name="Joe"))
    await db_session.commit()

    resp = await client.get("/api/v1/search?q=Acme", headers=auth_headers(admin_user))
    assert resp.status_code == 200, resp.text
    vendors = [r for r in resp.json() if r["entity_type"] == "vendor"]
    assert len(vendors) == 1
    assert vendors[0]["label"] == "Acme Plumbing Co"
    # Phase (b): deep-link route present and correct.
    assert vendors[0]["route"] == f"/vendors/{vendors[0]['entity_id']}"


@pytest.mark.asyncio
async def test_search_is_org_scoped(client, db_session):
    """Global search must only return entities from the caller's organization."""
    org_a = Organization(name="Org A", slug="org-a-search", plan="pro")
    org_b = Organization(name="Org B", slug="org-b-search", plan="pro")
    db_session.add_all([org_a, org_b])
    await db_session.commit()
    await db_session.refresh(org_a)
    await db_session.refresh(org_b)

    user_a = User(
        email="usera@search.com", display_name="A", password_hash=hash_password("x"),
        auth_provider="internal", role="admin", is_active=True, organization_id=org_a.id,
    )
    db_session.add(user_a)
    db_session.add(Vendor(company_name="Zebra Supplies A", contact_name="Al", organization_id=org_a.id))
    db_session.add(Vendor(company_name="Zebra Supplies B", contact_name="Bo", organization_id=org_b.id))
    await db_session.commit()
    await db_session.refresh(user_a)

    headers = {"Authorization": "Bearer " + create_access_token({"sub": str(user_a.id), "role": user_a.role})}
    resp = await client.get("/api/v1/search?q=Zebra", headers=headers)
    assert resp.status_code == 200, resp.text
    vendors = [r for r in resp.json() if r["entity_type"] == "vendor"]
    assert len(vendors) == 1
    assert vendors[0]["label"] == "Zebra Supplies A"


@pytest.mark.asyncio
async def test_search_results_all_carry_routes(client, admin_user, sample_office):
    resp = await client.get("/api/v1/search?q=Test", headers=auth_headers(admin_user))
    assert resp.status_code == 200
    for r in resp.json():
        assert "route" in r and r["route"]


# ── Phase (c): assistant intent dispatch ───────────────────────────────────────

@pytest.mark.asyncio
async def test_assistant_navigate_intent(client, db_session, monkeypatch):
    headers = await _make_org_user(db_session, "pro", "nav@test.com")

    async def fake_intent(prompt):
        return {"intent": "navigate", "params": {"destination": "leases_expiring"}}

    monkeypatch.setattr(ai_service, "parse_assistant_intent", fake_intent)
    resp = await client.post(
        "/api/v1/assistant", headers=headers, json={"prompt": "show leases expiring this quarter"}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["action_type"] == "navigate"
    assert data["route"] == "/leases?filter=expiring"


@pytest.mark.asyncio
async def test_assistant_create_ticket_proposes_for_editor(client, db_session, monkeypatch):
    headers = await _make_org_user(db_session, "pro", "edit@test.com", role="editor")

    async def fake_intent(prompt):
        return {"intent": "create_ticket", "params": {"subject": "No heat", "office_number": 12, "priority": "high"}}

    monkeypatch.setattr(ai_service, "parse_assistant_intent", fake_intent)
    resp = await client.post(
        "/api/v1/assistant", headers=headers, json={"prompt": "create a high-priority ticket for office 12"}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["action_type"] == "action"
    assert data["permitted"] is True
    assert data["confirmation_required"] is True
    assert data["proposal"]["endpoint"] == "/api/v1/maintenance-tickets"
    assert data["proposal"]["body"]["priority"] == "high"
    assert data["proposal"]["body"]["office_number"] == 12


@pytest.mark.asyncio
async def test_assistant_create_ticket_refused_for_viewer(client, db_session, monkeypatch):
    headers = await _make_org_user(db_session, "pro", "view@test.com", role="viewer")

    async def fake_intent(prompt):
        return {"intent": "create_ticket", "params": {"subject": "x", "office_number": None, "priority": "low"}}

    monkeypatch.setattr(ai_service, "parse_assistant_intent", fake_intent)
    resp = await client.post(
        "/api/v1/assistant", headers=headers, json={"prompt": "open a ticket"}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["permitted"] is False
    assert data["proposal"] is None


@pytest.mark.asyncio
async def test_assistant_gated_for_starter(client, db_session):
    headers = await _make_org_user(db_session, "starter", "starter5@test.com")
    resp = await client.post("/api/v1/assistant", headers=headers, json={"prompt": "x"})
    assert resp.status_code == 402


@pytest.mark.asyncio
async def test_assistant_degrades_when_unconfigured(client, db_session, monkeypatch):
    headers = await _make_org_user(db_session, "pro", "degrade5@test.com")

    async def fake_intent(prompt):
        raise ai_service.AIUnavailableError("AI assist is not configured.")

    monkeypatch.setattr(ai_service, "parse_assistant_intent", fake_intent)
    resp = await client.post("/api/v1/assistant", headers=headers, json={"prompt": "x"})
    assert resp.status_code == 503
