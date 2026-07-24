import pytest

from app.auth.password import hash_password
from app.models.organization import Organization
from app.models.user import User
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio


async def _org_admin(db_session, slug):
    org = Organization(name=slug, slug=slug, plan="pro", is_active=True)
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    user = User(
        email=f"{slug}@x.com", display_name=slug,
        password_hash=hash_password("Pass1234!"), auth_provider="internal",
        role="admin", is_active=True, organization_id=org.id,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return auth_headers(user)


async def test_create_manager(client, admin_user):
    resp = await client.post(
        "/api/v1/managers", headers=auth_headers(admin_user),
        json={"name": "Jane Doe", "email": "jane@example.com"},
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "Jane Doe"


async def test_duplicate_name_same_org_returns_409(client, db_session):
    # Uniqueness is scoped per organization, so use an org-scoped admin (the
    # default admin_user has organization_id NULL, where NULLs never collide).
    headers = await _org_admin(db_session, "cmgrorg")
    r1 = await client.post(
        "/api/v1/managers", headers=headers, json={"name": "Dup Mgr"}
    )
    assert r1.status_code == 201
    r2 = await client.post(
        "/api/v1/managers", headers=headers, json={"name": "Dup Mgr"}
    )
    # A duplicate name is rejected cleanly (409), not surfaced as a raw 500.
    assert r2.status_code == 409
    # The original manager still exists; no duplicate was created.
    listing = await client.get("/api/v1/managers", headers=headers)
    assert len([m for m in listing.json() if m["name"] == "Dup Mgr"]) == 1


async def test_same_name_allowed_across_orgs(client, db_session):
    for slug in ("xorg0", "xorg1"):
        headers = await _org_admin(db_session, slug)
        resp = await client.post(
            "/api/v1/managers", headers=headers,
            json={"name": "Shared Name"},
        )
        assert resp.status_code == 201
