"""Cross-tenant isolation guardrail tests.

Creates two independent organizations and asserts that a user in org B can never
reach org A's records by primary key. This is a permanent regression test for
the IDOR / cross-tenant data-leak class of bugs (attachments, lease
sub-resources, HQ-HVAC, landlord contacts). Every `{id}` endpoint must return
404 (never 200/204) for a foreign org's ids.
"""
import io
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.auth.password import hash_password
from app.config import settings
from app.models.organization import Organization
from app.models.user import User
from tests.conftest import auth_headers


@pytest.fixture(autouse=True)
def _tmp_upload_dir(tmp_path, monkeypatch):
    """Redirect attachment writes to a temp dir (default UPLOAD_DIR is unwritable)."""
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))


async def _make_org(db_session, slug: str) -> Organization:
    org = Organization(
        name=f"Org {slug}",
        slug=slug,
        plan="pro",  # pro plan entitles the 'hvac' feature used by HQ-HVAC
        is_active=True,
        trial_ends_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    return org


async def _make_admin(db_session, org: Organization, email: str) -> User:
    user = User(
        email=email,
        display_name=f"Admin {org.slug}",
        password_hash=hash_password("pw123456"),
        auth_provider="internal",
        role="admin",
        is_active=True,
        organization_id=org.id,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def two_orgs(db_session):
    org_a = await _make_org(db_session, "tenant-a")
    org_b = await _make_org(db_session, "tenant-b")
    admin_a = await _make_admin(db_session, org_a, "a@tenant-a.test")
    admin_b = await _make_admin(db_session, org_b, "b@tenant-b.test")
    return admin_a, admin_b


@pytest.mark.asyncio
async def test_attachments_cross_tenant_blocked(client, two_orgs):
    admin_a, admin_b = two_orgs

    # Org A creates a lease and uploads an attachment to it.
    lease = await client.post(
        "/api/v1/leases",
        headers=auth_headers(admin_a),
        json={"lease_name": "Confidential Lease A", "expiration_year": 2030},
    )
    assert lease.status_code == 201, lease.text
    lease_id = lease.json()["id"]

    upload = await client.post(
        f"/api/v1/lease/{lease_id}/attachments",
        headers=auth_headers(admin_a),
        files={"file": ("secret.txt", io.BytesIO(b"tenant-a secret"), "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    attachment_id = upload.json()["id"]

    # Org B must not be able to list, upload, download, delete, or count.
    assert (
        await client.get(f"/api/v1/lease/{lease_id}/attachments", headers=auth_headers(admin_b))
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/lease/{lease_id}/attachments",
            headers=auth_headers(admin_b),
            files={"file": ("evil.txt", io.BytesIO(b"x"), "text/plain")},
        )
    ).status_code == 404
    assert (
        await client.get(
            f"/api/v1/attachments/{attachment_id}/download", headers=auth_headers(admin_b)
        )
    ).status_code == 404
    assert (
        await client.delete(
            f"/api/v1/attachments/{attachment_id}", headers=auth_headers(admin_b)
        )
    ).status_code == 404

    counts = await client.get(
        "/api/v1/attachments/counts",
        params={"entity_type": "lease", "ids": lease_id},
        headers=auth_headers(admin_b),
    )
    assert counts.status_code == 200
    assert counts.json().get(lease_id, 0) == 0

    # Org A can still reach its own attachment.
    assert (
        await client.get(
            f"/api/v1/attachments/{attachment_id}/download", headers=auth_headers(admin_a)
        )
    ).status_code == 200


@pytest.mark.asyncio
async def test_lease_subresources_cross_tenant_blocked(client, two_orgs):
    admin_a, admin_b = two_orgs

    lease = await client.post(
        "/api/v1/leases",
        headers=auth_headers(admin_a),
        json={"lease_name": "Lease A", "expiration_year": 2030},
    )
    assert lease.status_code == 201, lease.text
    lease_id = lease.json()["id"]

    # clone / notes / accounting / renewals / options must all 404 for org B.
    assert (
        await client.post(f"/api/v1/leases/{lease_id}/clone", headers=auth_headers(admin_b))
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/leases/{lease_id}/notes",
            headers=auth_headers(admin_b),
            json={"note_text": "intrusion"},
        )
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/leases/{lease_id}/accounting", headers=auth_headers(admin_b))
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/leases/{lease_id}/renewals", headers=auth_headers(admin_b))
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/leases/{lease_id}/renewals",
            headers=auth_headers(admin_b),
            json={},
        )
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/leases/{lease_id}/options", headers=auth_headers(admin_b))
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/leases/{lease_id}/options",
            headers=auth_headers(admin_b),
            json={"option_type": "renewal"},
        )
    ).status_code == 404

    # Org A retains access to its own lease sub-resources.
    assert (
        await client.get(f"/api/v1/leases/{lease_id}/accounting", headers=auth_headers(admin_a))
    ).status_code in (200, 400)  # 400 only if the lease lacks accounting inputs


@pytest.mark.asyncio
async def test_landlord_contacts_cross_tenant_blocked(client, two_orgs):
    admin_a, admin_b = two_orgs

    landlord = await client.post(
        "/api/v1/landlords",
        headers=auth_headers(admin_a),
        json={"landlord_company": "Landlord A"},
    )
    assert landlord.status_code == 201, landlord.text
    landlord_id = landlord.json()["id"]

    contact = await client.post(
        f"/api/v1/landlords/{landlord_id}/contacts",
        headers=auth_headers(admin_a),
        json={"contact_name": "Jane"},
    )
    assert contact.status_code == 201, contact.text
    contact_id = contact.json()["id"]

    # Org B cannot add / update / delete contacts on org A's landlord.
    assert (
        await client.post(
            f"/api/v1/landlords/{landlord_id}/contacts",
            headers=auth_headers(admin_b),
            json={"contact_name": "Mallory"},
        )
    ).status_code == 404
    assert (
        await client.put(
            f"/api/v1/landlords/{landlord_id}/contacts/{contact_id}",
            headers=auth_headers(admin_b),
            json={"contact_name": "Hacked"},
        )
    ).status_code == 404
    assert (
        await client.delete(
            f"/api/v1/landlords/{landlord_id}/contacts/{contact_id}",
            headers=auth_headers(admin_b),
        )
    ).status_code == 404


@pytest.mark.asyncio
async def test_hq_hvac_cross_tenant_blocked(client, two_orgs):
    admin_a, admin_b = two_orgs

    pump = await client.post(
        "/api/v1/hq-hvac/heat-pumps",
        headers=auth_headers(admin_a),
        json={"unit_id": "HP-A1", "status": "active"},
    )
    assert pump.status_code == 201, pump.text
    pump_id = pump.json()["id"]

    # Org B cannot see org A's heat pump in a listing.
    listing = await client.get("/api/v1/hq-hvac/heat-pumps", headers=auth_headers(admin_b))
    assert listing.status_code == 200, listing.text
    assert all(p["id"] != pump_id for p in listing.json())

    # And cannot fetch / update / delete / add service logs by id.
    assert (
        await client.get(f"/api/v1/hq-hvac/heat-pumps/{pump_id}", headers=auth_headers(admin_b))
    ).status_code == 404
    assert (
        await client.put(
            f"/api/v1/hq-hvac/heat-pumps/{pump_id}",
            headers=auth_headers(admin_b),
            json={"status": "retired"},
        )
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/hq-hvac/heat-pumps/{pump_id}/service-log",
            headers=auth_headers(admin_b),
            json={"description": "tamper"},
        )
    ).status_code == 404
    assert (
        await client.delete(
            f"/api/v1/hq-hvac/heat-pumps/{pump_id}", headers=auth_headers(admin_b)
        )
    ).status_code == 404

    # Org A retains access to its own heat pump.
    assert (
        await client.get(f"/api/v1/hq-hvac/heat-pumps/{pump_id}", headers=auth_headers(admin_a))
    ).status_code == 200


@pytest.mark.asyncio
async def test_email_rules_cross_tenant_blocked(client, two_orgs):
    admin_a, admin_b = two_orgs

    created = await client.post(
        "/api/v1/email-rules/",
        headers=auth_headers(admin_a),
        json={
            "rule_name": "Org A Rule",
            "rule_type": "lease_expiration",
            "days_before": 30,
            "recipient_emails": ["ops@tenant-a.test"],
        },
    )
    assert created.status_code == 201, created.text
    rule_id = created.json()["id"]

    listed = await client.get("/api/v1/email-rules/", headers=auth_headers(admin_b))
    assert listed.status_code == 200, listed.text
    assert all(rule["id"] != rule_id for rule in listed.json())

    assert (
        await client.put(
            f"/api/v1/email-rules/{rule_id}",
            headers=auth_headers(admin_b),
            json={"rule_name": "Tampered"},
        )
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/email-rules/{rule_id}/test",
            headers=auth_headers(admin_b),
        )
    ).status_code == 404
    assert (
        await client.delete(
            f"/api/v1/email-rules/{rule_id}",
            headers=auth_headers(admin_b),
        )
    ).status_code == 404
