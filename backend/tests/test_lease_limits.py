"""Tests for the active-lease tier limit (``max_active_leases``).

Covers status classification, the org-scoped active-lease count across commercial
and residential leases, and HTTP 402 enforcement on both lease-creation surfaces.
"""
import pytest

from app.auth.password import hash_password
from app.models.lease import Lease
from app.models.office import Office
from app.models.organization import Organization
from app.models.resident import RentalUnit, ResidentLease
from app.models.user import User
from app.services import lease_limits
from tests.conftest import auth_headers


# ── Pure classification ───────────────────────────────────────────────────────

def test_commercial_status_classification():
    # No status / live statuses count as active.
    assert lease_limits.is_active_commercial_status(None) is True
    assert lease_limits.is_active_commercial_status("active") is True
    assert lease_limits.is_active_commercial_status("month_to_month") is True
    # Terminal statuses do not.
    assert lease_limits.is_active_commercial_status("expired") is False
    assert lease_limits.is_active_commercial_status("terminated") is False
    assert lease_limits.is_active_commercial_status("cancelled") is False


def test_resident_status_classification():
    assert lease_limits.is_active_resident_status("active") is True
    assert lease_limits.is_active_resident_status("pending") is True
    assert lease_limits.is_active_resident_status("draft") is False
    assert lease_limits.is_active_resident_status("ended") is False
    assert lease_limits.is_active_resident_status("terminated") is False


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _org_admin(db_session, *, plan: str, email: str, overrides=None):
    org = Organization(
        name=f"Org {email}",
        slug=f"org-{email[:8]}",
        plan=plan,
        entitlement_overrides=overrides or {},
    )
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    user = User(
        email=email,
        display_name="Admin",
        password_hash=hash_password("x"),
        auth_provider="internal",
        role="admin",
        is_active=True,
        organization_id=org.id,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return org, user


# ── Count across both lease surfaces ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_count_active_leases_spans_commercial_and_residential(db_session):
    org, _ = await _org_admin(db_session, plan="starter", email="count@test.com")

    db_session.add(Office(office_number=1, region_number=1, location_type="office",
                          location_name="O", is_active=True, organization_id=org.id))
    # Active + terminated + no-status commercial leases.
    db_session.add(Lease(lease_name="Active", expiration_year=2030, status="active",
                         organization_id=org.id))
    db_session.add(Lease(lease_name="Terminated", expiration_year=2030,
                         status="terminated", organization_id=org.id))
    db_session.add(Lease(lease_name="NoStatus", expiration_year=2030,
                         organization_id=org.id))

    unit = RentalUnit(unit_number="U1", name="U1", organization_id=org.id, status="available")
    db_session.add(unit)
    await db_session.flush()
    db_session.add(ResidentLease(unit_id=unit.id, status="active", organization_id=org.id))
    db_session.add(ResidentLease(unit_id=unit.id, status="draft", organization_id=org.id))
    await db_session.commit()

    # 2 commercial (active + no-status) + 1 residential active = 3.
    assert await lease_limits.count_active_leases(db_session, org.id) == 3


# ── Commercial enforcement ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_commercial_lease_creation_blocked_at_limit(client, db_session):
    org, admin = await _org_admin(
        db_session, plan="starter", email="commercial@test.com",
        overrides={"max_active_leases": 1},
    )
    first = await client.post("/api/v1/leases", headers=auth_headers(admin), json={
        "lease_name": "First", "expiration_year": 2030, "status": "active"})
    assert first.status_code == 201, first.text

    second = await client.post("/api/v1/leases", headers=auth_headers(admin), json={
        "lease_name": "Second", "expiration_year": 2030, "status": "active"})
    assert second.status_code == 402, second.text
    assert "active lease limit" in second.json()["detail"].lower()


@pytest.mark.asyncio
async def test_commercial_terminated_lease_bypasses_limit(client, db_session):
    org, admin = await _org_admin(
        db_session, plan="starter", email="terminated@test.com",
        overrides={"max_active_leases": 1},
    )
    await client.post("/api/v1/leases", headers=auth_headers(admin), json={
        "lease_name": "Active", "expiration_year": 2030, "status": "active"})
    # A terminated lease does not count as active, so it can still be created.
    resp = await client.post("/api/v1/leases", headers=auth_headers(admin), json={
        "lease_name": "Terminated", "expiration_year": 2030, "status": "terminated"})
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_enterprise_unlimited_active_leases(client, db_session):
    org, admin = await _org_admin(db_session, plan="enterprise", email="ent@test.com")
    for i in range(3):
        resp = await client.post("/api/v1/leases", headers=auth_headers(admin), json={
            "lease_name": f"L{i}", "expiration_year": 2030, "status": "active"})
        assert resp.status_code == 201, resp.text


# ── Residential enforcement ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_residential_lease_creation_blocked_at_limit(client, db_session):
    org, admin = await _org_admin(
        db_session, plan="starter", email="resi@test.com",
        overrides={"max_active_leases": 1},
    )
    unit = RentalUnit(unit_number="A1", name="Unit A", organization_id=org.id, status="available")
    db_session.add(unit)
    await db_session.commit()
    await db_session.refresh(unit)

    first = await client.post("/api/v1/leasing/leases", headers=auth_headers(admin), json={
        "unit_id": str(unit.id), "status": "active"})
    assert first.status_code == 201, first.text

    second = await client.post("/api/v1/leasing/leases", headers=auth_headers(admin), json={
        "unit_id": str(unit.id), "status": "active"})
    assert second.status_code == 402, second.text


@pytest.mark.asyncio
async def test_residential_draft_lease_bypasses_limit(client, db_session):
    org, admin = await _org_admin(
        db_session, plan="starter", email="residraft@test.com",
        overrides={"max_active_leases": 1},
    )
    unit = RentalUnit(unit_number="B1", name="Unit B", organization_id=org.id, status="available")
    db_session.add(unit)
    await db_session.commit()
    await db_session.refresh(unit)

    await client.post("/api/v1/leasing/leases", headers=auth_headers(admin), json={
        "unit_id": str(unit.id), "status": "active"})
    # A draft lease is not active and can still be created at the cap.
    resp = await client.post("/api/v1/leasing/leases", headers=auth_headers(admin), json={
        "unit_id": str(unit.id), "status": "draft"})
    assert resp.status_code == 201, resp.text
