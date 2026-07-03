"""Tests for the tenant/resident domain (Phase 2.1 — org-as-lessor leasing).

Covers rental units, resident records, resident leases with occupant links,
unit occupancy sync, active-lease overlap protection, and role gating.
"""

import pytest

from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/leasing"


async def _make_unit(client, admin_user, office_id=None, unit_number="101", status="available"):
    payload = {"unit_number": unit_number, "status": status, "market_rent": "1500.00"}
    if office_id:
        payload["office_id"] = str(office_id)
    resp = await client.post(f"{BASE}/units", json=payload, headers=auth_headers(admin_user))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _make_resident(client, admin_user, first="Jane", last="Doe"):
    resp = await client.post(
        f"{BASE}/residents",
        json={"first_name": first, "last_name": last, "email": f"{first}@x.com"},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_create_unit(client, admin_user):
    unit = await _make_unit(client, admin_user)
    assert unit["unit_number"] == "101"
    assert unit["status"] == "available"
    assert unit["currency"] == "USD"


async def test_unit_rejects_bad_status(client, admin_user):
    resp = await client.post(
        f"{BASE}/units",
        json={"unit_number": "9", "status": "bogus"},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 422


async def test_unit_rejects_non_usd(client, admin_user):
    resp = await client.post(
        f"{BASE}/units",
        json={"unit_number": "9", "currency": "EUR"},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 422


async def test_duplicate_unit_number_same_office_conflicts(client, admin_user, sample_office):
    await _make_unit(client, admin_user, office_id=sample_office.id, unit_number="A1")
    resp = await client.post(
        f"{BASE}/units",
        json={"unit_number": "A1", "office_id": str(sample_office.id)},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 409


async def test_viewer_cannot_write_but_can_read(client, admin_user, viewer_user):
    unit = await _make_unit(client, admin_user)
    # viewer read OK
    resp = await client.get(f"{BASE}/units", headers=auth_headers(viewer_user))
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    # viewer write forbidden
    resp = await client.post(
        f"{BASE}/units", json={"unit_number": "202"}, headers=auth_headers(viewer_user)
    )
    assert resp.status_code == 403


async def test_create_resident(client, admin_user):
    resident = await _make_resident(client, admin_user)
    assert resident["last_name"] == "Doe"
    assert resident["status"] == "prospect"


async def test_create_lease_with_occupant_marks_unit_occupied(client, admin_user):
    unit = await _make_unit(client, admin_user)
    resident = await _make_resident(client, admin_user)
    resp = await client.post(
        f"{BASE}/leases",
        json={
            "unit_id": unit["id"],
            "status": "active",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "rent_amount": "1500.00",
            "occupants": [
                {"resident_id": resident["id"], "role": "primary", "is_primary": True}
            ],
        },
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 201, resp.text
    lease = resp.json()
    assert len(lease["occupants"]) == 1
    assert lease["occupants"][0]["resident_id"] == resident["id"]
    assert lease["occupants"][0]["resident"]["last_name"] == "Doe"

    # Unit should now be derived as occupied.
    unit_resp = await client.get(f"{BASE}/units/{unit['id']}", headers=auth_headers(admin_user))
    assert unit_resp.json()["status"] == "occupied"


async def test_overlapping_active_lease_conflicts(client, admin_user):
    unit = await _make_unit(client, admin_user)
    r1 = await _make_resident(client, admin_user, first="A")
    r2 = await _make_resident(client, admin_user, first="B")
    ok = await client.post(
        f"{BASE}/leases",
        json={
            "unit_id": unit["id"],
            "status": "active",
            "start_date": "2026-01-01",
            "end_date": "2026-06-30",
            "occupants": [{"resident_id": r1["id"]}],
        },
        headers=auth_headers(admin_user),
    )
    assert ok.status_code == 201
    conflict = await client.post(
        f"{BASE}/leases",
        json={
            "unit_id": unit["id"],
            "status": "active",
            "start_date": "2026-03-01",
            "end_date": "2026-09-30",
            "occupants": [{"resident_id": r2["id"]}],
        },
        headers=auth_headers(admin_user),
    )
    assert conflict.status_code == 409


async def test_draft_leases_do_not_conflict(client, admin_user):
    unit = await _make_unit(client, admin_user)
    for _ in range(2):
        resp = await client.post(
            f"{BASE}/leases",
            json={"unit_id": unit["id"], "status": "draft"},
            headers=auth_headers(admin_user),
        )
        assert resp.status_code == 201
    # Unit remains available while only drafts exist.
    unit_resp = await client.get(f"{BASE}/units/{unit['id']}", headers=auth_headers(admin_user))
    assert unit_resp.json()["status"] == "available"


async def test_end_before_start_rejected(client, admin_user):
    unit = await _make_unit(client, admin_user)
    resp = await client.post(
        f"{BASE}/leases",
        json={
            "unit_id": unit["id"],
            "start_date": "2026-12-31",
            "end_date": "2026-01-01",
        },
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 422


async def test_ending_lease_frees_unit(client, admin_user):
    unit = await _make_unit(client, admin_user)
    resident = await _make_resident(client, admin_user)
    created = await client.post(
        f"{BASE}/leases",
        json={
            "unit_id": unit["id"],
            "status": "active",
            "occupants": [{"resident_id": resident["id"]}],
        },
        headers=auth_headers(admin_user),
    )
    lease_id = created.json()["id"]
    # End the lease.
    resp = await client.patch(
        f"{BASE}/leases/{lease_id}",
        json={"status": "ended"},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 200
    unit_resp = await client.get(f"{BASE}/units/{unit['id']}", headers=auth_headers(admin_user))
    assert unit_resp.json()["status"] == "available"


async def test_cannot_delete_unit_with_active_lease(client, admin_user):
    unit = await _make_unit(client, admin_user)
    resident = await _make_resident(client, admin_user)
    await client.post(
        f"{BASE}/leases",
        json={
            "unit_id": unit["id"],
            "status": "active",
            "occupants": [{"resident_id": resident["id"]}],
        },
        headers=auth_headers(admin_user),
    )
    resp = await client.delete(f"{BASE}/units/{unit['id']}", headers=auth_headers(admin_user))
    assert resp.status_code == 409


async def test_duplicate_occupant_rejected(client, admin_user):
    unit = await _make_unit(client, admin_user)
    resident = await _make_resident(client, admin_user)
    resp = await client.post(
        f"{BASE}/leases",
        json={
            "unit_id": unit["id"],
            "occupants": [
                {"resident_id": resident["id"]},
                {"resident_id": resident["id"]},
            ],
        },
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 422


async def test_filter_leases_by_resident(client, admin_user):
    unit = await _make_unit(client, admin_user)
    resident = await _make_resident(client, admin_user)
    await client.post(
        f"{BASE}/leases",
        json={"unit_id": unit["id"], "occupants": [{"resident_id": resident["id"]}]},
        headers=auth_headers(admin_user),
    )
    resp = await client.get(
        f"{BASE}/leases",
        params={"resident_id": resident["id"]},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_occupancy_summary(client, admin_user):
    u1 = await _make_unit(client, admin_user, unit_number="1")
    await _make_unit(client, admin_user, unit_number="2")
    await _make_unit(client, admin_user, unit_number="3", status="unavailable")
    resident = await _make_resident(client, admin_user)
    await client.post(
        f"{BASE}/leases",
        json={
            "unit_id": u1["id"],
            "status": "active",
            "occupants": [{"resident_id": resident["id"]}],
        },
        headers=auth_headers(admin_user),
    )
    resp = await client.get(f"{BASE}/occupancy", headers=auth_headers(admin_user))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_units"] == 3
    assert data["counts"]["occupied"] == 1
    assert data["counts"]["available"] == 1
    assert data["counts"]["unavailable"] == 1
    # Rate = occupied / (occupied + available) = 1/2.
    assert data["occupancy_rate"] == 0.5


async def test_manual_unavailable_status_preserved(client, admin_user):
    unit = await _make_unit(client, admin_user, status="unavailable")
    resident = await _make_resident(client, admin_user)
    # Even adding an active lease keeps a manually-held unit unavailable.
    await client.post(
        f"{BASE}/leases",
        json={
            "unit_id": unit["id"],
            "status": "active",
            "occupants": [{"resident_id": resident["id"]}],
        },
        headers=auth_headers(admin_user),
    )
    unit_resp = await client.get(f"{BASE}/units/{unit['id']}", headers=auth_headers(admin_user))
    assert unit_resp.json()["status"] == "unavailable"
