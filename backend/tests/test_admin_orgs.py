import pytest
from sqlalchemy import select

from app.auth.password import hash_password
from app.models.activity_log import ActivityLog
from app.models.organization import Organization
from app.models.user import User
from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_super_admin_can_rename_org(client, db_session):
    """A super-admin can change an existing organization's name via the
    management (admin) API."""
    org = Organization(name="Old Name", slug="old-name", plan="starter", is_active=True)
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)

    super_admin = User(
        email="root@test.com",
        display_name="Root",
        password_hash=hash_password("RootPass123!"),
        auth_provider="internal",
        role="admin",
        is_active=True,
        is_super_admin=True,
    )
    db_session.add(super_admin)
    await db_session.commit()
    await db_session.refresh(super_admin)

    resp = await client.patch(
        f"/admin/v1/orgs/{org.id}",
        headers=auth_headers(super_admin),
        json={"name": "New Name"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "New Name"

    await db_session.refresh(org)
    assert org.name == "New Name"


@pytest.mark.asyncio
async def test_rename_org_rejects_blank_name(client, db_session):
    org = Organization(name="Keep Name", slug="keep-name", plan="starter", is_active=True)
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)

    super_admin = User(
        email="root2@test.com",
        display_name="Root2",
        password_hash=hash_password("RootPass123!"),
        auth_provider="internal",
        role="admin",
        is_active=True,
        is_super_admin=True,
    )
    db_session.add(super_admin)
    await db_session.commit()
    await db_session.refresh(super_admin)

    resp = await client.patch(
        f"/admin/v1/orgs/{org.id}",
        headers=auth_headers(super_admin),
        json={"name": "   "},
    )
    assert resp.status_code == 422, resp.text

    await db_session.refresh(org)
    assert org.name == "Keep Name"


@pytest.mark.asyncio
async def test_super_admin_can_view_org_detail(client, db_session):
    """A super-admin can fetch an organization's detail. Regression test for the
    detail endpoint omitting the required ``risk_label`` field, which made
    ``GET /admin/v1/orgs/{id}`` fail with a 500 surfaced in the admin UI as
    "Organization not found"."""
    org = Organization(name="Viewable Org", slug="viewable-org", plan="pro", is_active=True)
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)

    super_admin = User(
        email="root3@test.com",
        display_name="Root3",
        password_hash=hash_password("RootPass123!"),
        auth_provider="internal",
        role="admin",
        is_active=True,
        is_super_admin=True,
    )
    db_session.add(super_admin)
    await db_session.commit()
    await db_session.refresh(super_admin)

    resp = await client.get(
        f"/admin/v1/orgs/{org.id}",
        headers=auth_headers(super_admin),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(org.id)
    assert body["name"] == "Viewable Org"
    assert "risk_label" in body


@pytest.mark.asyncio
async def test_entitlement_override_patch_logs_before_and_after(client, db_session):
    org = Organization(
        name="Override Org",
        slug="override-org",
        plan="starter",
        is_active=True,
        entitlement_overrides={"max_seats": 5},
    )
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)

    super_admin = User(
        email="root4@test.com",
        display_name="Root4",
        password_hash=hash_password("RootPass123!"),
        auth_provider="internal",
        role="admin",
        is_active=True,
        is_super_admin=True,
    )
    db_session.add(super_admin)
    await db_session.commit()
    await db_session.refresh(super_admin)

    resp = await client.patch(
        f"/admin/v1/orgs/{org.id}",
        headers=auth_headers(super_admin),
        json={"entitlement_overrides": {"max_seats": 10}},
    )
    assert resp.status_code == 200, resp.text

    audit = (
        await db_session.execute(
            select(ActivityLog).where(ActivityLog.entity_id == org.id).order_by(ActivityLog.created_at.desc())
        )
    ).scalar_one()
    assert audit.changes["entitlement_overrides"]["before"] == {"max_seats": 5}
    assert audit.changes["entitlement_overrides"]["after"] == {"max_seats": 10}
