"""Tests for the self-storage domain (org-as-operator).

Covers storage units (incl. bulk creation and conditioned space), agreements
with resident occupants, the move-in / move-out lifecycle and unit-status sync,
rate changes, the delinquency → lien → auction workflow, recurring billing that
posts through the shared AR/GL, payments, occupancy summary, role gating, and
cross-tenant isolation.

Storage tenants are ordinary Residents, so residents are created through the
existing leasing router. The default test users have no organization, which
bypasses the ``require_category`` guard (category gating is covered in
``test_categories.py``).
"""
import pytest

from app.auth.password import hash_password
from app.models.organization import Organization
from app.models.user import User
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/self-storage"
LEASING = "/api/v1/leasing"
AR = "/api/v1/ar"


async def _make_unit(client, admin_user, *, unit_number="A100", facility_id=None, **extra):
    payload = {"unit_number": unit_number, **extra}
    if facility_id:
        payload["facility_id"] = str(facility_id)
    resp = await client.post(f"{BASE}/units", json=payload, headers=auth_headers(admin_user))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _make_resident(client, admin_user, first="Sam", last="Storer"):
    resp = await client.post(
        f"{LEASING}/residents",
        json={"first_name": first, "last_name": last, "email": f"{first}@x.com"},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _make_agreement(client, admin_user, unit_id, resident_id, *, status="draft", rent="150.00"):
    resp = await client.post(
        f"{BASE}/agreements",
        json={
            "unit_id": unit_id,
            "status": status,
            "rent_amount": rent,
            "occupants": [{"resident_id": resident_id, "is_primary": True, "role": "primary"}],
        },
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── Facilities (self-storage "Property") ─────────────────────────────────────

async def _make_facility(client, admin_user, *, name="Downtown Storage", **extra):
    resp = await client.post(
        f"{BASE}/facilities",
        json={"name": name, **extra},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_facility_crud_and_unit_link(client, admin_user):
    facility = await _make_facility(
        client, admin_user, name="North Facility", city="Denver", state="CO"
    )
    assert facility["name"] == "North Facility"
    assert facility["is_active"] is True

    # A unit can be parented to the facility (its own data set, not an Office).
    unit = await _make_unit(
        client, admin_user, unit_number="F1", facility_id=facility["id"]
    )
    assert unit["facility_id"] == facility["id"]

    # Listing units can be scoped by facility_id.
    listed = await client.get(
        f"{BASE}/units",
        params={"facility_id": facility["id"]},
        headers=auth_headers(admin_user),
    )
    assert listed.status_code == 200
    assert [u["id"] for u in listed.json()] == [unit["id"]]

    # Update + list facilities.
    upd = await client.patch(
        f"{BASE}/facilities/{facility['id']}",
        json={"is_active": False, "manager_name": "Pat"},
        headers=auth_headers(admin_user),
    )
    assert upd.status_code == 200
    assert upd.json()["is_active"] is False
    assert upd.json()["manager_name"] == "Pat"

    all_facilities = await client.get(
        f"{BASE}/facilities", headers=auth_headers(admin_user)
    )
    assert facility["id"] in {f["id"] for f in all_facilities.json()}


async def test_viewer_cannot_create_facility(client, admin_user, viewer_user):
    resp = await client.post(
        f"{BASE}/facilities",
        json={"name": "Nope"},
        headers=auth_headers(viewer_user),
    )
    assert resp.status_code == 403


async def test_facility_stores_full_address_and_details(client, admin_user):
    """A property captures a robust set of fields, not just a few basics."""
    facility = await _make_facility(
        client, admin_user,
        name="Uptown Storage",
        code="UPT",
        facility_number=7,
        address_line_1="123 Main St",
        address_line_2="Suite 4",
        city="Denver",
        state="CO",
        zip_code="80202",
        phone="555-1000",
        email="ops@uptown.example",
        gate_hours="6am-10pm",
        access_hours="24/7",
        total_units=250,
        notes="Flagship",
    )
    assert facility["address_line_1"] == "123 Main St"
    assert facility["address_line_2"] == "Suite 4"
    assert facility["zip_code"] == "80202"
    assert facility["phone"] == "555-1000"
    assert facility["email"] == "ops@uptown.example"
    assert facility["gate_hours"] == "6am-10pm"
    assert facility["access_hours"] == "24/7"
    assert facility["total_units"] == 250
    assert facility["code"] == "UPT"
    assert facility["facility_number"] == 7


async def test_facility_requires_name(client, admin_user):
    resp = await client.post(
        f"{BASE}/facilities",
        json={"name": "   "},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 422


# ── Managers (self-storage — its own data set) ───────────────────────────────

async def _make_storage_manager(client, admin_user, *, name="Pat Manager", **extra):
    resp = await client.post(
        f"{BASE}/managers",
        json={"name": name, **extra},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_storage_manager_crud(client, admin_user):
    manager = await _make_storage_manager(
        client, admin_user, name="Jordan Ops", email="jordan@x.com", phone="555-2000"
    )
    assert manager["name"] == "Jordan Ops"
    assert manager["email"] == "jordan@x.com"

    listed = await client.get(f"{BASE}/managers", headers=auth_headers(admin_user))
    assert listed.status_code == 200
    assert manager["id"] in {m["id"] for m in listed.json()}

    upd = await client.patch(
        f"{BASE}/managers/{manager['id']}",
        json={"phone": "555-9999"},
        headers=auth_headers(admin_user),
    )
    assert upd.status_code == 200
    assert upd.json()["phone"] == "555-9999"

    delete = await client.delete(
        f"{BASE}/managers/{manager['id']}", headers=auth_headers(admin_user)
    )
    assert delete.status_code == 204


async def test_storage_manager_name_is_unique(client, db_session, admin_user):
    # Uniqueness is scoped per organization, so use an org-scoped admin (the
    # default admin_user has organization_id NULL, where NULLs never collide).
    org = Organization(
        name="MgrOrg", slug="mgrorg", plan="pro", is_active=True,
        enabled_categories=["self_storage"],
    )
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    user = User(
        email="mgrorg@x.com", display_name="MgrOrg", password_hash=hash_password("Pass1234!"),
        auth_provider="internal", role="admin", is_active=True, organization_id=org.id,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    await _make_storage_manager(client, user, name="Dup Manager")
    resp = await client.post(
        f"{BASE}/managers",
        json={"name": "Dup Manager"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 409


async def test_viewer_cannot_create_manager(client, admin_user, viewer_user):
    resp = await client.post(
        f"{BASE}/managers",
        json={"name": "Nope"},
        headers=auth_headers(viewer_user),
    )
    assert resp.status_code == 403


async def test_facility_assigned_to_manager(client, admin_user):
    manager = await _make_storage_manager(client, admin_user, name="Assigned Mgr")
    facility = await _make_facility(
        client, admin_user, name="Managed Facility", manager_id=manager["id"]
    )
    assert facility["manager_id"] == manager["id"]
    # The manager is returned nested and the free-text name is kept in sync.
    assert facility["manager"]["name"] == "Assigned Mgr"
    assert facility["manager_name"] == "Assigned Mgr"


async def test_facility_rejects_unknown_manager(client, admin_user):
    import uuid as _uuid

    resp = await client.post(
        f"{BASE}/facilities",
        json={"name": "Bad Mgr", "manager_id": str(_uuid.uuid4())},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 404


async def test_deleting_manager_detaches_facility(client, admin_user):
    manager = await _make_storage_manager(client, admin_user, name="Temp Mgr")
    facility = await _make_facility(
        client, admin_user, name="Detach Facility", manager_id=manager["id"]
    )
    delete = await client.delete(
        f"{BASE}/managers/{manager['id']}", headers=auth_headers(admin_user)
    )
    assert delete.status_code == 204
    fetched = await client.get(
        f"{BASE}/facilities/{facility['id']}", headers=auth_headers(admin_user)
    )
    assert fetched.status_code == 200
    assert fetched.json()["manager_id"] is None


# ── Units ────────────────────────────────────────────────────────────────────

async def test_create_unit_with_conditioned_space(client, admin_user):
    unit = await _make_unit(
        client, admin_user,
        unit_number="B12",
        size_label="10x10",
        size_tier="medium",
        width_ft="10",
        length_ft="10",
        square_feet="100",
        climate_controlled=True,
        unit_type="interior",
        street_rate="175.00",
    )
    assert unit["climate_controlled"] is True
    assert unit["size_tier"] == "medium"
    assert unit["status"] == "available"
    assert unit["currency"] == "USD"


async def test_unit_rejects_bad_enums(client, admin_user):
    bad_type = await client.post(
        f"{BASE}/units",
        json={"unit_number": "x", "unit_type": "bogus"},
        headers=auth_headers(admin_user),
    )
    assert bad_type.status_code == 422
    bad_status = await client.post(
        f"{BASE}/units",
        json={"unit_number": "x", "status": "bogus"},
        headers=auth_headers(admin_user),
    )
    assert bad_status.status_code == 422


async def test_bulk_create_units(client, admin_user):
    resp = await client.post(
        f"{BASE}/units/bulk",
        json={"count": 5, "start_number": 1, "prefix": "C", "size_tier": "small", "street_rate": "90.00"},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 201, resp.text
    units = resp.json()
    assert len(units) == 5
    assert {u["unit_number"] for u in units} == {"C1", "C2", "C3", "C4", "C5"}


async def test_viewer_cannot_create_unit(client, admin_user, viewer_user):
    resp = await client.post(
        f"{BASE}/units", json={"unit_number": "z"}, headers=auth_headers(viewer_user)
    )
    assert resp.status_code == 403


# ── Agreements + occupancy sync ──────────────────────────────────────────────

async def test_active_agreement_marks_unit_occupied(client, admin_user):
    unit = await _make_unit(client, admin_user)
    resident_id = await _make_resident(client, admin_user)
    await _make_agreement(client, admin_user, unit["id"], resident_id, status="active")
    got = await client.get(f"{BASE}/units/{unit['id']}", headers=auth_headers(admin_user))
    assert got.json()["status"] == "occupied"


async def test_second_active_agreement_on_unit_rejected(client, admin_user):
    unit = await _make_unit(client, admin_user)
    r1 = await _make_resident(client, admin_user, first="One")
    r2 = await _make_resident(client, admin_user, first="Two")
    await _make_agreement(client, admin_user, unit["id"], r1, status="active")
    resp = await client.post(
        f"{BASE}/agreements",
        json={
            "unit_id": unit["id"],
            "status": "active",
            "occupants": [{"resident_id": r2, "is_primary": True}],
        },
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 400


async def test_move_in_and_move_out_lifecycle(client, admin_user):
    unit = await _make_unit(client, admin_user)
    resident_id = await _make_resident(client, admin_user)
    agreement = await _make_agreement(client, admin_user, unit["id"], resident_id, rent="200.00")

    mi = await client.post(
        f"{BASE}/agreements/{agreement['id']}/move-in",
        json={"move_in_date": "2026-01-05"},
        headers=auth_headers(admin_user),
    )
    assert mi.status_code == 200, mi.text
    assert mi.json()["status"] == "active"
    unit_after = await client.get(f"{BASE}/units/{unit['id']}", headers=auth_headers(admin_user))
    assert unit_after.json()["status"] == "occupied"
    assert unit_after.json()["in_place_rate"] == "200.00"

    mo = await client.post(
        f"{BASE}/agreements/{agreement['id']}/move-out",
        json={"move_out_date": "2026-06-01"},
        headers=auth_headers(admin_user),
    )
    assert mo.status_code == 200, mo.text
    assert mo.json()["status"] == "ended"
    unit_free = await client.get(f"{BASE}/units/{unit['id']}", headers=auth_headers(admin_user))
    assert unit_free.json()["status"] == "available"


async def test_move_in_requires_occupants(client, admin_user):
    unit = await _make_unit(client, admin_user)
    resp = await client.post(
        f"{BASE}/agreements",
        json={"unit_id": unit["id"], "status": "draft", "occupants": []},
        headers=auth_headers(admin_user),
    )
    agreement_id = resp.json()["id"]
    mi = await client.post(
        f"{BASE}/agreements/{agreement_id}/move-in", json={}, headers=auth_headers(admin_user)
    )
    assert mi.status_code == 400


async def test_change_rate_updates_agreement_and_unit(client, admin_user):
    unit = await _make_unit(client, admin_user)
    resident_id = await _make_resident(client, admin_user)
    agreement = await _make_agreement(client, admin_user, unit["id"], resident_id, status="active")
    resp = await client.post(
        f"{BASE}/agreements/{agreement['id']}/change-rate",
        json={"new_rate": "225.50"},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["rent_amount"] == "225.50"
    unit_after = await client.get(f"{BASE}/units/{unit['id']}", headers=auth_headers(admin_user))
    assert unit_after.json()["in_place_rate"] == "225.50"


# ── Delinquency → lien → auction workflow ────────────────────────────────────

async def test_lien_workflow_progression(client, admin_user):
    unit = await _make_unit(client, admin_user)
    resident_id = await _make_resident(client, admin_user)
    agreement = await _make_agreement(client, admin_user, unit["id"], resident_id, status="active")
    aid = agreement["id"]

    steps = ["late", "overlock", "lien_notice", "auction_scheduled", "auctioned"]
    for step in steps:
        resp = await client.post(
            f"{BASE}/agreements/{aid}/lien-events",
            json={"step": step, "amount_due": "150.00"},
            headers=auth_headers(admin_user),
        )
        assert resp.status_code == 201, (step, resp.text)

    events = await client.get(f"{BASE}/agreements/{aid}/lien-events", headers=auth_headers(admin_user))
    assert [e["step"] for e in events.json()] == steps

    agreement_after = await client.get(f"{BASE}/agreements/{aid}", headers=auth_headers(admin_user))
    assert agreement_after.json()["status"] == "auctioned"
    unit_after = await client.get(f"{BASE}/units/{unit['id']}", headers=auth_headers(admin_user))
    assert unit_after.json()["status"] == "auction"


async def test_lien_must_start_with_late(client, admin_user):
    unit = await _make_unit(client, admin_user)
    resident_id = await _make_resident(client, admin_user)
    agreement = await _make_agreement(client, admin_user, unit["id"], resident_id, status="active")
    resp = await client.post(
        f"{BASE}/agreements/{agreement['id']}/lien-events",
        json={"step": "auctioned"},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 400


async def test_lien_rejects_illegal_transition(client, admin_user):
    unit = await _make_unit(client, admin_user)
    resident_id = await _make_resident(client, admin_user)
    agreement = await _make_agreement(client, admin_user, unit["id"], resident_id, status="active")
    aid = agreement["id"]
    await client.post(
        f"{BASE}/agreements/{aid}/lien-events", json={"step": "late"}, headers=auth_headers(admin_user)
    )
    # late → auction_scheduled is not allowed (must overlock/notice first)
    resp = await client.post(
        f"{BASE}/agreements/{aid}/lien-events",
        json={"step": "auction_scheduled"},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 400


async def test_lien_redeemed_restores_agreement(client, admin_user):
    unit = await _make_unit(client, admin_user)
    resident_id = await _make_resident(client, admin_user)
    agreement = await _make_agreement(client, admin_user, unit["id"], resident_id, status="active")
    aid = agreement["id"]
    r_late = await client.post(f"{BASE}/agreements/{aid}/lien-events", json={"step": "late"}, headers=auth_headers(admin_user))
    assert r_late.status_code == 201, r_late.text
    r_over = await client.post(f"{BASE}/agreements/{aid}/lien-events", json={"step": "overlock"}, headers=auth_headers(admin_user))
    assert r_over.status_code == 201, r_over.text
    redeemed = await client.post(
        f"{BASE}/agreements/{aid}/lien-events", json={"step": "redeemed"}, headers=auth_headers(admin_user)
    )
    assert redeemed.status_code == 201, redeemed.text
    agreement_after = await client.get(f"{BASE}/agreements/{aid}", headers=auth_headers(admin_user))
    assert agreement_after.json()["status"] == "active"
    unit_after = await client.get(f"{BASE}/units/{unit['id']}", headers=auth_headers(admin_user))
    assert unit_after.json()["status"] == "occupied"


# ── Billing through shared AR/GL ─────────────────────────────────────────────

async def _seed_billable(client, admin_user, *, rent="150.00"):
    unit = await _make_unit(client, admin_user, street_rate="175.00")
    resident_id = await _make_resident(client, admin_user)
    agreement = await _make_agreement(client, admin_user, unit["id"], resident_id, status="active", rent=rent)
    charge = await client.post(
        f"{BASE}/charges",
        json={
            "storage_agreement_id": agreement["id"],
            "amount": rent,
            "day_of_month": 1,
            "start_date": "2026-01-01",
            "revenue_account_code": "4100",
        },
        headers=auth_headers(admin_user),
    )
    assert charge.status_code == 201, charge.text
    return unit, agreement, charge.json()


async def test_run_billing_posts_to_ar(client, admin_user):
    await _seed_billable(client, admin_user, rent="100.00")
    run = await client.post(f"{BASE}/run-billing?as_of=2026-03-15", headers=auth_headers(admin_user))
    assert run.status_code == 200, run.text
    # Jan, Feb, Mar due by 2026-03-15.
    assert run.json()["generated"] == 3

    # Idempotent re-run.
    rerun = await client.post(f"{BASE}/run-billing?as_of=2026-03-15", headers=auth_headers(admin_user))
    assert rerun.json()["generated"] == 0

    # Storage invoices show up in the shared AR aging report.
    aging = await client.get(f"{AR}/aging", headers=auth_headers(admin_user))
    assert aging.status_code == 200
    assert float(aging.json()["grand_total"]) == pytest.approx(300.00)


async def test_record_payment_reduces_ar_balance(client, admin_user):
    _, _, charge = await _seed_billable(client, admin_user, rent="120.00")
    run = await client.post(f"{BASE}/run-billing?as_of=2026-01-15", headers=auth_headers(admin_user))
    invoice_id = run.json()["invoice_ids"][0]

    pay = await client.post(
        f"{BASE}/payments",
        json={"invoice_id": invoice_id, "amount": "120.00", "method": "ach"},
        headers=auth_headers(admin_user),
    )
    assert pay.status_code == 200, pay.text
    assert pay.json()["amount"] == "120.00"

    aging = await client.get(f"{AR}/aging", headers=auth_headers(admin_user))
    assert float(aging.json()["grand_total"]) == pytest.approx(0.0)


async def test_billing_requires_finance_role(client, admin_user, editor_user):
    await _seed_billable(client, admin_user)
    resp = await client.post(f"{BASE}/run-billing", headers=auth_headers(editor_user))
    assert resp.status_code == 403


# ── Occupancy summary ────────────────────────────────────────────────────────

async def test_occupancy_summary(client, admin_user):
    # One occupied, one vacant.
    u1 = await _make_unit(client, admin_user, unit_number="OS1", street_rate="100.00")
    await _make_unit(client, admin_user, unit_number="OS2", street_rate="100.00")
    resident_id = await _make_resident(client, admin_user)
    await _make_agreement(client, admin_user, u1["id"], resident_id, status="active", rent="90.00")

    summary = await client.get(f"{BASE}/occupancy-summary", headers=auth_headers(admin_user))
    assert summary.status_code == 200, summary.text
    data = summary.json()
    assert data["total_units"] == 2
    assert data["occupied_units"] == 1
    assert data["physical_occupancy_pct"] == pytest.approx(50.0)


# ── Cross-tenant isolation ───────────────────────────────────────────────────

async def test_units_are_org_scoped(client, db_session, admin_user):
    # admin_user has no org → its units carry organization_id NULL. Create a
    # second org-scoped admin and confirm it cannot see admin_user's units.
    await _make_unit(client, admin_user, unit_number="ISO1")

    org = Organization(
        name="Other", slug="other", plan="pro", is_active=True,
        enabled_categories=["self_storage"],
    )
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    other = User(
        email="other@x.com", display_name="Other", password_hash=hash_password("Pass1234!"),
        auth_provider="internal", role="admin", is_active=True, organization_id=org.id,
    )
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)

    listing = await client.get(f"{BASE}/units", headers=auth_headers(other))
    assert listing.status_code == 200
    assert listing.json() == []
