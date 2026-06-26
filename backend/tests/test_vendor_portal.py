from datetime import datetime, timezone, timedelta

import pytest
import pytest_asyncio

from app.models.office import Manager
from app.models.vendor import Vendor
from app.models.maintenance_ticket import MaintenanceTicket
from tests.conftest import auth_headers


@pytest_asyncio.fixture
async def sample_vendor(db_session):
    vendor = Vendor(
        company_name="Acme Repairs",
        contact_name="Vince Vendor",
        contact_email="vince@acme.test",
        portal_token="vendor-token-123",
        portal_token_expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db_session.add(vendor)
    await db_session.commit()
    await db_session.refresh(vendor)
    return vendor


def _vendor_headers(token: str) -> dict[str, str]:
    return {"X-Vendor-Token": token}


# ─── Assigning a vendor on the ticket ───────────────────────────────────────

@pytest.mark.asyncio
async def test_create_ticket_with_vendor(client, editor_user, sample_office, sample_category, sample_vendor):
    resp = await client.post(
        "/api/v1/maintenance-tickets",
        headers=auth_headers(editor_user),
        json={
            "subject": "Leaky faucet",
            "priority": "low",
            "category_id": str(sample_category.id),
            "office_id": str(sample_office.id),
            "description": "Drip drip",
            "vendor_id": str(sample_vendor.id),
        },
    )
    assert resp.status_code == 201
    assert resp.json()["vendor_id"] == str(sample_vendor.id)


# ─── Email on creation (manager + vendor) ────────────────────────────────────

@pytest.mark.asyncio
async def test_ticket_created_emails_manager_and_vendor(
    client, db_session, editor_user, sample_category, sample_vendor, monkeypatch
):
    # Office with a manager that has an email.
    manager = Manager(name="Manny Manager", email="manny@office.test")
    db_session.add(manager)
    await db_session.commit()
    await db_session.refresh(manager)

    from app.models.office import Office
    office = Office(
        office_number=200,
        location_type="office",
        location_name="HQ",
        is_active=True,
        manager_id=manager.id,
    )
    db_session.add(office)
    await db_session.commit()
    await db_session.refresh(office)

    sent: list[str] = []

    async def fake_send_email(to, subject, html):
        sent.append(to)
        return True

    monkeypatch.setattr("app.tasks.ticket_email.send_email", fake_send_email)

    resp = await client.post(
        "/api/v1/maintenance-tickets",
        headers=auth_headers(editor_user),
        json={
            "subject": "HVAC down",
            "priority": "low",
            "category_id": str(sample_category.id),
            "office_id": str(office.id),
            "description": "No cooling",
            "vendor_id": str(sample_vendor.id),
        },
    )
    assert resp.status_code == 201
    assert "manny@office.test" in sent
    assert "vince@acme.test" in sent


# ─── Portal auth ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_portal_requires_token(client):
    resp = await client.get("/api/v1/vendor-portal/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_portal_profile(client, sample_vendor):
    resp = await client.get("/api/v1/vendor-portal/me", headers=_vendor_headers(sample_vendor.portal_token))
    assert resp.status_code == 200
    assert resp.json()["company_name"] == "Acme Repairs"


# ─── Portal: update ticket details ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_portal_update_ticket_details(
    client, db_session, sample_office, sample_category, sample_vendor
):
    ticket = MaintenanceTicket(
        subject="Repaint wall",
        priority="low",
        status="open",
        category_id=sample_category.id,
        office_id=sample_office.id,
        description="Old paint",
        created_by_id=None,  # set below
        vendor_id=sample_vendor.id,
    )
    # created_by_id is required; create a quick user.
    from app.models.user import User
    from app.auth.password import hash_password
    user = User(
        email="creator@test.com",
        display_name="Creator",
        password_hash=hash_password("pw"),
        auth_provider="internal",
        role="editor",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    ticket.created_by_id = user.id
    db_session.add(ticket)
    await db_session.commit()
    await db_session.refresh(ticket)

    resp = await client.patch(
        f"/api/v1/vendor-portal/tickets/{ticket.id}",
        headers=_vendor_headers(sample_vendor.portal_token),
        json={"description": "Fresh coat applied", "technician_name": "Tech T"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["description"] == "Fresh coat applied"
    assert body["technician_name"] == "Tech T"


@pytest.mark.asyncio
async def test_portal_cannot_update_other_vendors_ticket(
    client, db_session, sample_office, sample_category, sample_vendor
):
    other = Vendor(company_name="Other Co", portal_token="other-token")
    db_session.add(other)
    from app.models.user import User
    from app.auth.password import hash_password
    user = User(
        email="c2@test.com", display_name="C2", password_hash=hash_password("pw"),
        auth_provider="internal", role="editor", is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(other)
    await db_session.refresh(user)

    ticket = MaintenanceTicket(
        subject="Not yours", priority="low", status="open",
        category_id=sample_category.id, office_id=sample_office.id,
        description="x", created_by_id=user.id, vendor_id=other.id,
    )
    db_session.add(ticket)
    await db_session.commit()
    await db_session.refresh(ticket)

    resp = await client.patch(
        f"/api/v1/vendor-portal/tickets/{ticket.id}",
        headers=_vendor_headers(sample_vendor.portal_token),
        json={"description": "hijack"},
    )
    assert resp.status_code == 404


# ─── Portal: additional contacts CRUD ───────────────────────────────────────

@pytest.mark.asyncio
async def test_portal_contacts_crud(client, sample_vendor):
    token = sample_vendor.portal_token

    # Initially empty
    resp = await client.get("/api/v1/vendor-portal/contacts", headers=_vendor_headers(token))
    assert resp.status_code == 200
    assert resp.json() == []

    # Create — entity scoping is forced server-side regardless of body.
    resp = await client.post(
        "/api/v1/vendor-portal/contacts",
        headers=_vendor_headers(token),
        json={
            "entity_type": "landlord",  # should be overridden to "vendor"
            "entity_id": "00000000-0000-0000-0000-000000000000",
            "contact_name": "Extra Contact",
            "email": "extra@acme.test",
        },
    )
    assert resp.status_code == 201
    created = resp.json()
    assert created["entity_type"] == "vendor"
    assert created["entity_id"] == str(sample_vendor.id)
    contact_id = created["id"]

    # Update
    resp = await client.put(
        f"/api/v1/vendor-portal/contacts/{contact_id}",
        headers=_vendor_headers(token),
        json={"phone": "555-1234"},
    )
    assert resp.status_code == 200
    assert resp.json()["phone"] == "555-1234"

    # List shows it
    resp = await client.get("/api/v1/vendor-portal/contacts", headers=_vendor_headers(token))
    assert len(resp.json()) == 1

    # Delete
    resp = await client.delete(
        f"/api/v1/vendor-portal/contacts/{contact_id}", headers=_vendor_headers(token)
    )
    assert resp.status_code == 204

    resp = await client.get("/api/v1/vendor-portal/contacts", headers=_vendor_headers(token))
    assert resp.json() == []
