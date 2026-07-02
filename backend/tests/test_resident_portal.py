"""Tests for the resident portal + communications (Phase 2.2)."""

import pytest

from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio

LEASING = "/api/v1/leasing"
PORTAL = "/api/v1"
ANN = "/api/v1/announcements"


async def _seed_resident_with_lease(client, admin_user, sample_office):
    unit = await client.post(
        f"{LEASING}/units",
        json={"unit_number": "1A", "office_id": str(sample_office.id)},
        headers=auth_headers(admin_user),
    )
    unit_id = unit.json()["id"]
    resident = await client.post(
        f"{LEASING}/residents",
        json={"first_name": "Rex", "last_name": "Tenant", "email": "rex@x.com", "phone": "+15551230000"},
        headers=auth_headers(admin_user),
    )
    resident_id = resident.json()["id"]
    await client.post(
        f"{LEASING}/leases",
        json={
            "unit_id": unit_id,
            "status": "active",
            "rent_amount": "1800.00",
            "security_deposit": "1800.00",
            "occupants": [{"resident_id": resident_id, "is_primary": True}],
        },
        headers=auth_headers(admin_user),
    )
    return resident_id


async def _activate_portal(client, admin_user, resident_id):
    invite = await client.post(
        f"{PORTAL}/resident-portal/invite",
        json={"resident_id": resident_id},
        headers=auth_headers(admin_user),
    )
    assert invite.status_code == 200, invite.text
    signup_token = invite.json()["signup_token"]
    session = await client.post(
        f"{PORTAL}/resident-portal/signup", json={"token": signup_token}
    )
    assert session.status_code == 200, session.text
    return session.json()["portal_token"]


def _pt(token):
    return {"X-Resident-Token": token}


async def test_invite_and_signup_flow(client, admin_user, sample_office):
    resident_id = await _seed_resident_with_lease(client, admin_user, sample_office)
    token = await _activate_portal(client, admin_user, resident_id)
    me = await client.get(f"{PORTAL}/resident-portal/me", headers=_pt(token))
    assert me.status_code == 200
    assert me.json()["first_name"] == "Rex"


async def test_portal_requires_token(client):
    resp = await client.get(f"{PORTAL}/resident-portal/me")
    assert resp.status_code == 401


async def test_invalid_token_rejected(client):
    resp = await client.get(f"{PORTAL}/resident-portal/me", headers=_pt("nope"))
    assert resp.status_code == 401


async def test_portal_leases_and_balance(client, admin_user, sample_office):
    resident_id = await _seed_resident_with_lease(client, admin_user, sample_office)
    token = await _activate_portal(client, admin_user, resident_id)

    leases = await client.get(f"{PORTAL}/resident-portal/leases", headers=_pt(token))
    assert leases.status_code == 200
    body = leases.json()
    assert len(body) == 1
    assert body[0]["unit_number"] == "1A"
    assert body[0]["rent_amount"] == "1800.00"

    bal = await client.get(f"{PORTAL}/resident-portal/balance", headers=_pt(token))
    assert bal.status_code == 200
    assert bal.json()["monthly_rent"] == "1800.00"
    assert bal.json()["balance_due"] == "0.00"


async def test_submit_maintenance_request_feeds_ticketing(client, admin_user, sample_office):
    resident_id = await _seed_resident_with_lease(client, admin_user, sample_office)
    token = await _activate_portal(client, admin_user, resident_id)

    resp = await client.post(
        f"{PORTAL}/resident-portal/maintenance-requests",
        json={"subject": "Leaky faucet", "description": "Kitchen sink drips", "priority": "high"},
        headers=_pt(token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["subject"] == "Leaky faucet"

    # Resident sees their own request.
    listing = await client.get(
        f"{PORTAL}/resident-portal/maintenance-requests", headers=_pt(token)
    )
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    # Staff sees it in the main ticket queue.
    staff = await client.get(
        "/api/v1/maintenance-tickets", headers=auth_headers(admin_user)
    )
    assert staff.status_code == 200
    subjects = [t["subject"] for t in staff.json()["items"]]
    assert "Leaky faucet" in subjects


async def test_announcement_crud_and_send(client, admin_user, sample_office):
    resident_id = await _seed_resident_with_lease(client, admin_user, sample_office)
    token = await _activate_portal(client, admin_user, resident_id)

    created = await client.post(
        ANN,
        json={
            "title": "Water shutoff",
            "body": "Water off Tuesday 9-11am.",
            "channels": ["portal", "email", "sms"],
        },
        headers=auth_headers(admin_user),
    )
    assert created.status_code == 201, created.text
    ann_id = created.json()["id"]
    assert created.json()["status"] == "draft"

    sent = await client.post(f"{ANN}/{ann_id}/send", headers=auth_headers(admin_user))
    assert sent.status_code == 200, sent.text
    result = sent.json()
    assert result["recipients"] == 1
    # SMS/email transports are unconfigured in tests → best-effort not delivered.
    assert result["emailed"] == 0
    assert result["texted"] == 0

    # Resident sees the announcement in the portal.
    portal_ann = await client.get(
        f"{PORTAL}/resident-portal/announcements", headers=_pt(token)
    )
    assert portal_ann.status_code == 200
    assert len(portal_ann.json()) == 1
    assert portal_ann.json()[0]["title"] == "Water shutoff"


async def test_announcement_cannot_send_twice(client, admin_user):
    created = await client.post(
        ANN,
        json={"title": "Hi", "body": "There", "channels": ["portal"]},
        headers=auth_headers(admin_user),
    )
    ann_id = created.json()["id"]
    await client.post(f"{ANN}/{ann_id}/send", headers=auth_headers(admin_user))
    again = await client.post(f"{ANN}/{ann_id}/send", headers=auth_headers(admin_user))
    assert again.status_code == 409


async def test_announcement_rejects_bad_channel(client, admin_user):
    resp = await client.post(
        ANN,
        json={"title": "x", "body": "y", "channels": ["carrier-pigeon"]},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 422


async def test_sent_announcement_cannot_be_edited(client, admin_user):
    created = await client.post(
        ANN,
        json={"title": "x", "body": "y", "channels": ["portal"]},
        headers=auth_headers(admin_user),
    )
    ann_id = created.json()["id"]
    await client.post(f"{ANN}/{ann_id}/send", headers=auth_headers(admin_user))
    resp = await client.patch(
        f"{ANN}/{ann_id}", json={"title": "z"}, headers=auth_headers(admin_user)
    )
    assert resp.status_code == 409


async def test_announcement_audience_filter_by_status(client, admin_user, sample_office):
    # One current resident, one prospect; target only 'current'.
    r1 = await client.post(
        f"{LEASING}/residents",
        json={"first_name": "Cur", "last_name": "Rent", "status": "current"},
        headers=auth_headers(admin_user),
    )
    await client.post(
        f"{LEASING}/residents",
        json={"first_name": "Pro", "last_name": "Spect", "status": "prospect"},
        headers=auth_headers(admin_user),
    )
    created = await client.post(
        ANN,
        json={
            "title": "Current only",
            "body": "hi",
            "channels": ["portal"],
            "audience_resident_status": "current",
        },
        headers=auth_headers(admin_user),
    )
    ann_id = created.json()["id"]
    sent = await client.post(f"{ANN}/{ann_id}/send", headers=auth_headers(admin_user))
    assert sent.json()["recipients"] == 1


async def test_viewer_cannot_create_announcement(client, viewer_user):
    resp = await client.post(
        ANN,
        json={"title": "x", "body": "y", "channels": ["portal"]},
        headers=auth_headers(viewer_user),
    )
    assert resp.status_code == 403
