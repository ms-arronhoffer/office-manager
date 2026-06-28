import pytest
from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_client_portal_invite_signup_and_self_service(client, admin_user):
    # Admin creates a landlord to grant portal access to.
    created = await client.post(
        "/api/v1/landlords",
        headers=auth_headers(admin_user),
        json={"contact_name": "Portal Owner", "landlord_company": "Owner LLC"},
    )
    assert created.status_code == 201, created.text
    landlord_id = created.json()["id"]

    # Admin mints a single-use signup invite.
    invite = await client.post(
        "/api/v1/client-portal/invite",
        headers=auth_headers(admin_user),
        json={"entity_type": "landlord", "entity_id": landlord_id},
    )
    assert invite.status_code == 200, invite.text
    signup_token = invite.json()["signup_token"]
    assert signup_token
    assert invite.json()["signup_url"].endswith(signup_token)

    # Redeeming the signup token activates the portal and returns a portal token.
    signup = await client.post("/api/v1/client-portal/signup", json={"token": signup_token})
    assert signup.status_code == 200, signup.text
    portal_token = signup.json()["portal_token"]
    assert signup.json()["entity_type"] == "landlord"

    # The signup token is single-use.
    reused = await client.post("/api/v1/client-portal/signup", json={"token": signup_token})
    assert reused.status_code == 401

    headers = {"X-Portal-Token": portal_token}

    # Read-only profile.
    me = await client.get("/api/v1/client-portal/me", headers=headers)
    assert me.status_code == 200, me.text
    assert me.json()["name"] == "Owner LLC"
    assert me.json()["entity_type"] == "landlord"

    # Create a secondary contact; entity scoping is forced server-side.
    new_contact = await client.post(
        "/api/v1/client-portal/contacts",
        headers=headers,
        json={
            "entity_type": "vendor",  # should be ignored/overridden
            "entity_id": "00000000-0000-0000-0000-000000000000",
            "contact_name": "Secondary Sam",
            "email": "sam@owner.test",
        },
    )
    assert new_contact.status_code == 201, new_contact.text
    contact = new_contact.json()
    assert contact["entity_type"] == "landlord"
    assert contact["entity_id"] == landlord_id

    # List contacts shows it.
    listed = await client.get("/api/v1/client-portal/contacts", headers=headers)
    assert listed.status_code == 200
    assert any(c["id"] == contact["id"] for c in listed.json())

    # Update the contact.
    upd = await client.put(
        f"/api/v1/client-portal/contacts/{contact['id']}",
        headers=headers,
        json={"phone": "555-2020"},
    )
    assert upd.status_code == 200, upd.text
    assert upd.json()["phone"] == "555-2020"

    # Upload a document.
    doc = await client.post(
        "/api/v1/client-portal/documents",
        headers=headers,
        files={"file": ("note.txt", b"hello world", "text/plain")},
    )
    assert doc.status_code == 201, doc.text
    assert doc.json()["original_filename"] == "note.txt"

    docs = await client.get("/api/v1/client-portal/documents", headers=headers)
    assert docs.status_code == 200
    assert len(docs.json()) == 1

    # Delete the contact.
    deleted = await client.delete(
        f"/api/v1/client-portal/contacts/{contact['id']}", headers=headers
    )
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_client_portal_requires_token(client):
    resp = await client.get("/api/v1/client-portal/me")
    assert resp.status_code == 401

    bad = await client.get("/api/v1/client-portal/me", headers={"X-Portal-Token": "nope"})
    assert bad.status_code == 401


@pytest.mark.asyncio
async def test_client_portal_invite_rejects_bad_entity_type(client, admin_user):
    resp = await client.post(
        "/api/v1/client-portal/invite",
        headers=auth_headers(admin_user),
        json={"entity_type": "vendor", "entity_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert resp.status_code == 422


# ─── Helpers for the enhanced-portal tests ───────────────────────────────────

async def _create_landlord(client, admin_user, *, company="Acme Owner LLC", **extra):
    payload = {"contact_name": "Owner", "landlord_company": company}
    payload.update(extra)
    resp = await client.post(
        "/api/v1/landlords", headers=auth_headers(admin_user), json=payload
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _activate_portal(client, admin_user, entity_id, entity_type="landlord"):
    invite = await client.post(
        "/api/v1/client-portal/invite",
        headers=auth_headers(admin_user),
        json={"entity_type": entity_type, "entity_id": entity_id},
    )
    assert invite.status_code == 200, invite.text
    signup = await client.post(
        "/api/v1/client-portal/signup", json={"token": invite.json()["signup_token"]}
    )
    assert signup.status_code == 200, signup.text
    return signup.json()["portal_token"]


# ─── Phase 1: document download + delete ─────────────────────────────────────

@pytest.mark.asyncio
async def test_portal_document_download_and_cross_entity_isolation(client, admin_user):
    landlord_a = await _create_landlord(client, admin_user, company="A LLC")
    landlord_b = await _create_landlord(client, admin_user, company="B LLC")
    token_a = await _activate_portal(client, admin_user, landlord_a)
    token_b = await _activate_portal(client, admin_user, landlord_b)

    up = await client.post(
        "/api/v1/client-portal/documents",
        headers={"X-Portal-Token": token_a},
        files={"file": ("a.txt", b"secret-a", "text/plain")},
    )
    assert up.status_code == 201, up.text
    doc_id = up.json()["id"]

    # Owner can download.
    dl = await client.get(
        f"/api/v1/client-portal/documents/{doc_id}/download",
        headers={"X-Portal-Token": token_a},
    )
    assert dl.status_code == 200
    assert dl.content == b"secret-a"

    # A different entity's token cannot see or download it.
    dl_b = await client.get(
        f"/api/v1/client-portal/documents/{doc_id}/download",
        headers={"X-Portal-Token": token_b},
    )
    assert dl_b.status_code == 404


@pytest.mark.asyncio
async def test_portal_document_delete_only_own_uploads(client, admin_user, db_session):
    from app.models.attachment import Attachment

    landlord_id = await _create_landlord(client, admin_user)
    token = await _activate_portal(client, admin_user, landlord_id)

    # Client-uploaded document can be removed.
    up = await client.post(
        "/api/v1/client-portal/documents",
        headers={"X-Portal-Token": token},
        files={"file": ("mine.txt", b"hi", "text/plain")},
    )
    assert up.status_code == 201
    own_id = up.json()["id"]

    # An internally-uploaded document (uploaded_by != client_portal) is off-limits.
    internal = Attachment(
        entity_type="landlord",
        entity_id=landlord_id,
        original_filename="internal.txt",
        stored_filename="internal-stored.txt",
        content_type="text/plain",
        file_size=4,
        uploaded_by="admin@test.com",
        description="internal",
    )
    db_session.add(internal)
    await db_session.commit()
    await db_session.refresh(internal)

    blocked = await client.delete(
        f"/api/v1/client-portal/documents/{internal.id}",
        headers={"X-Portal-Token": token},
    )
    assert blocked.status_code == 403

    ok = await client.delete(
        f"/api/v1/client-portal/documents/{own_id}",
        headers={"X-Portal-Token": token},
    )
    assert ok.status_code == 204


# ─── Phase 3: change requests ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_portal_change_request_lifecycle(client, admin_user):
    landlord_id = await _create_landlord(client, admin_user, contact_phone="000")
    token = await _activate_portal(client, admin_user, landlord_id)

    # Unknown field is rejected.
    bad = await client.post(
        "/api/v1/client-portal/change-requests",
        headers={"X-Portal-Token": token},
        json={"proposed_changes": {"tax_id": "hacked"}},
    )
    assert bad.status_code == 422

    # Empty payload rejected.
    empty = await client.post(
        "/api/v1/client-portal/change-requests",
        headers={"X-Portal-Token": token},
        json={"proposed_changes": {}},
    )
    assert empty.status_code == 422

    # Valid request.
    cr = await client.post(
        "/api/v1/client-portal/change-requests",
        headers={"X-Portal-Token": token},
        json={
            "proposed_changes": {"contact_phone": "555-7777", "city": "Metropolis"},
            "message": "Please update our phone.",
        },
    )
    assert cr.status_code == 201, cr.text
    cr_id = cr.json()["id"]
    assert cr.json()["status"] == "pending"

    # Client can list their requests.
    mine = await client.get(
        "/api/v1/client-portal/change-requests", headers={"X-Portal-Token": token}
    )
    assert mine.status_code == 200
    assert any(r["id"] == cr_id for r in mine.json())

    # Admin sees it pending.
    admin_list = await client.get(
        "/api/v1/client-portal/admin/change-requests",
        headers=auth_headers(admin_user),
        params={"entity_type": "landlord", "entity_id": landlord_id, "status_filter": "pending"},
    )
    assert admin_list.status_code == 200, admin_list.text
    assert len(admin_list.json()) == 1

    # Approve applies the changes to the landlord.
    approve = await client.post(
        f"/api/v1/client-portal/admin/change-requests/{cr_id}/approve",
        headers=auth_headers(admin_user),
        json={"review_note": "Looks good"},
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["status"] == "approved"

    landlord = await client.get(
        f"/api/v1/landlords/{landlord_id}", headers=auth_headers(admin_user)
    )
    assert landlord.json()["contact_phone"] == "555-7777"
    assert landlord.json()["city"] == "Metropolis"

    # Re-reviewing a resolved request is a conflict.
    again = await client.post(
        f"/api/v1/client-portal/admin/change-requests/{cr_id}/reject",
        headers=auth_headers(admin_user),
        json={},
    )
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_portal_change_request_reject(client, admin_user):
    landlord_id = await _create_landlord(client, admin_user, contact_phone="111")
    token = await _activate_portal(client, admin_user, landlord_id)

    cr = await client.post(
        "/api/v1/client-portal/change-requests",
        headers={"X-Portal-Token": token},
        json={"proposed_changes": {"contact_phone": "999"}},
    )
    cr_id = cr.json()["id"]
    rej = await client.post(
        f"/api/v1/client-portal/admin/change-requests/{cr_id}/reject",
        headers=auth_headers(admin_user),
        json={"review_note": "Not verified"},
    )
    assert rej.status_code == 200
    assert rej.json()["status"] == "rejected"

    # Landlord phone unchanged.
    landlord = await client.get(
        f"/api/v1/landlords/{landlord_id}", headers=auth_headers(admin_user)
    )
    assert landlord.json()["contact_phone"] == "111"


# ─── Phase 4: status, revoke, rotate ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_portal_admin_status_transitions(client, admin_user):
    landlord_id = await _create_landlord(client, admin_user)

    # No account yet.
    s0 = await client.get(
        "/api/v1/client-portal/admin/status",
        headers=auth_headers(admin_user),
        params={"entity_type": "landlord", "entity_id": landlord_id},
    )
    assert s0.status_code == 200
    assert s0.json()["status"] == "none"

    # Invited (not yet activated).
    await client.post(
        "/api/v1/client-portal/invite",
        headers=auth_headers(admin_user),
        json={"entity_type": "landlord", "entity_id": landlord_id},
    )
    s1 = await client.get(
        "/api/v1/client-portal/admin/status",
        headers=auth_headers(admin_user),
        params={"entity_type": "landlord", "entity_id": landlord_id},
    )
    assert s1.json()["status"] == "invited"


@pytest.mark.asyncio
async def test_portal_revoke_blocks_access(client, admin_user):
    landlord_id = await _create_landlord(client, admin_user)
    token = await _activate_portal(client, admin_user, landlord_id)

    # Works before revoke.
    ok = await client.get("/api/v1/client-portal/me", headers={"X-Portal-Token": token})
    assert ok.status_code == 200

    rev = await client.post(
        "/api/v1/client-portal/admin/revoke",
        headers=auth_headers(admin_user),
        json={"entity_type": "landlord", "entity_id": landlord_id},
    )
    assert rev.status_code == 200
    assert rev.json()["status"] == "revoked"

    # Token no longer works.
    after = await client.get("/api/v1/client-portal/me", headers={"X-Portal-Token": token})
    assert after.status_code == 401


@pytest.mark.asyncio
async def test_portal_rotate_issues_new_token(client, admin_user):
    landlord_id = await _create_landlord(client, admin_user)
    old_token = await _activate_portal(client, admin_user, landlord_id)

    rot = await client.post(
        "/api/v1/client-portal/admin/rotate",
        headers=auth_headers(admin_user),
        json={"entity_type": "landlord", "entity_id": landlord_id},
    )
    assert rot.status_code == 200, rot.text
    new_token = rot.json()["portal_token"]
    assert new_token != old_token

    # New token works, old one is invalid.
    assert (
        await client.get("/api/v1/client-portal/me", headers={"X-Portal-Token": new_token})
    ).status_code == 200
    assert (
        await client.get("/api/v1/client-portal/me", headers={"X-Portal-Token": old_token})
    ).status_code == 401


# ─── Phase 5: portfolio (offices / leases / maintenance) ─────────────────────

async def _seed_portfolio(db_session, landlord_id, *, expiration_days=30):
    """Attach an office, lease and ticket to a landlord; return office_id."""
    import uuid as _uuid
    from datetime import date, timedelta
    from app.models.office import Office
    from app.models.lease import Lease
    from app.models.landlord import Landlord, landlord_offices
    from app.models.maintenance_ticket import MaintenanceTicket, TicketCategory
    from app.models.user import User

    office = Office(office_number=42, location_type="lease", location_name="Metro Tower")
    db_session.add(office)
    await db_session.commit()
    await db_session.refresh(office)

    await db_session.execute(
        landlord_offices.insert().values(landlord_id=_uuid.UUID(landlord_id), office_id=office.id)
    )
    lease = Lease(
        office_id=office.id,
        lease_name="HQ Lease",
        expiration_year=date.today().year,
        lease_expiration=date.today() + timedelta(days=expiration_days),
        payment_amount=99999,
    )
    db_session.add(lease)
    cat = TicketCategory(name="Plumbing")
    db_session.add(cat)
    await db_session.commit()
    await db_session.refresh(cat)
    creator = (await db_session.execute(
        __import__("sqlalchemy").select(User).limit(1)
    )).scalars().first()
    ticket = MaintenanceTicket(
        subject="Leak", priority="high", status="open",
        category_id=cat.id, office_id=office.id, description="x", created_by_id=creator.id,
    )
    db_session.add(ticket)
    await db_session.commit()
    return str(office.id)


@pytest.mark.asyncio
async def test_portal_portfolio_scoped_and_no_financials(client, admin_user, db_session):
    landlord_id = await _create_landlord(client, admin_user, company="Owner LLC")
    token = await _activate_portal(client, admin_user, landlord_id)
    office_id = await _seed_portfolio(db_session, landlord_id)
    h = {"X-Portal-Token": token}

    offices = await client.get("/api/v1/client-portal/offices", headers=h)
    assert offices.status_code == 200, offices.text
    assert [o["id"] for o in offices.json()] == [office_id]
    assert offices.json()[0]["lease_count"] == 1

    leases = await client.get("/api/v1/client-portal/leases", headers=h)
    assert leases.status_code == 200
    assert len(leases.json()) == 1
    assert leases.json()[0]["expiring_soon"] is True
    # Financial fields are never exposed.
    assert "payment_amount" not in leases.json()[0]

    tickets = await client.get("/api/v1/client-portal/maintenance", headers=h)
    assert tickets.status_code == 200
    assert len(tickets.json()) == 1

    summary = await client.get("/api/v1/client-portal/summary", headers=h)
    assert summary.json() == {"office_count": 1, "lease_count": 1, "expiring_soon": 1, "open_tickets": 1}


@pytest.mark.asyncio
async def test_portal_portfolio_cross_entity_isolation(client, admin_user, db_session):
    a = await _create_landlord(client, admin_user, company="A LLC")
    b = await _create_landlord(client, admin_user, company="B LLC")
    token_b = await _activate_portal(client, admin_user, b)
    await _seed_portfolio(db_session, a)

    assert (await client.get("/api/v1/client-portal/offices", headers={"X-Portal-Token": token_b})).json() == []
    assert (await client.get("/api/v1/client-portal/leases", headers={"X-Portal-Token": token_b})).json() == []
