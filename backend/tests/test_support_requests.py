"""Tests for the Support Requests API."""
import pytest

from app.models.organization import Organization
from app.models.site_settings import SiteSettings
from app.models.support_request import SupportRequest
from app.models.user import User
from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_any_user_can_create_support_request(client, viewer_user: User, db_session):
    resp = await client.post(
        "/api/v1/support-requests",
        json={"subject": "Need help", "message": "Something is broken"},
        headers=auth_headers(viewer_user),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["subject"] == "Need help"
    assert body["status"] == "open"
    assert body["requester_email"] == viewer_user.email
    assert body["requester_name"] == viewer_user.display_name

    from sqlalchemy import select

    rows = (await db_session.execute(select(SupportRequest))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_create_validates_required_fields(client, viewer_user: User):
    resp = await client.post(
        "/api/v1/support-requests",
        json={"subject": "", "message": ""},
        headers=auth_headers(viewer_user),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_requires_admin(client, viewer_user: User, admin_user: User):
    await client.post(
        "/api/v1/support-requests",
        json={"subject": "S", "message": "M"},
        headers=auth_headers(viewer_user),
    )

    forbidden = await client.get(
        "/api/v1/support-requests", headers=auth_headers(viewer_user)
    )
    assert forbidden.status_code == 403

    listing = await client.get(
        "/api/v1/support-requests", headers=auth_headers(admin_user)
    )
    assert listing.status_code == 200
    assert len(listing.json()) == 1


@pytest.mark.asyncio
async def test_update_status_and_filter(client, viewer_user: User, admin_user: User):
    created = await client.post(
        "/api/v1/support-requests",
        json={"subject": "S", "message": "M"},
        headers=auth_headers(viewer_user),
    )
    req_id = created.json()["id"]

    updated = await client.patch(
        f"/api/v1/support-requests/{req_id}",
        json={"status": "resolved"},
        headers=auth_headers(admin_user),
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "resolved"

    open_only = await client.get(
        "/api/v1/support-requests?status=open", headers=auth_headers(admin_user)
    )
    assert open_only.json() == []

    resolved_only = await client.get(
        "/api/v1/support-requests?status=resolved", headers=auth_headers(admin_user)
    )
    assert len(resolved_only.json()) == 1


@pytest.mark.asyncio
async def test_update_rejects_invalid_status(client, viewer_user: User, admin_user: User):
    created = await client.post(
        "/api/v1/support-requests",
        json={"subject": "S", "message": "M"},
        headers=auth_headers(viewer_user),
    )
    req_id = created.json()["id"]
    resp = await client.patch(
        f"/api/v1/support-requests/{req_id}",
        json={"status": "bogus"},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_delete_support_request(client, viewer_user: User, admin_user: User, db_session):
    created = await client.post(
        "/api/v1/support-requests",
        json={"subject": "S", "message": "M"},
        headers=auth_headers(viewer_user),
    )
    req_id = created.json()["id"]
    resp = await client.delete(
        f"/api/v1/support-requests/{req_id}", headers=auth_headers(admin_user)
    )
    assert resp.status_code == 204

    from sqlalchemy import select

    rows = (await db_session.execute(select(SupportRequest))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_email_without_configured_address(client, viewer_user: User, admin_user: User):
    created = await client.post(
        "/api/v1/support-requests",
        json={"subject": "S", "message": "M"},
        headers=auth_headers(viewer_user),
    )
    req_id = created.json()["id"]
    resp = await client.post(
        f"/api/v1/support-requests/{req_id}/email", headers=auth_headers(admin_user)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["sent"] is False
    assert body["support_email"] is None


@pytest.mark.asyncio
async def test_email_forwards_to_configured_address(
    client, db_session, monkeypatch
):
    """When a support_email is configured, the email endpoint forwards to it."""
    org = Organization(name="Acme", slug="acme")
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)

    from app.auth.password import hash_password

    user = User(
        email="member@acme.com",
        display_name="Member",
        password_hash=hash_password("pw123456"),
        auth_provider="internal",
        role="admin",
        is_active=True,
        organization_id=org.id,
    )
    db_session.add(user)
    db_session.add(
        SiteSettings(organization_id=org.id, app_name="Acme", support_email="help@acme.com")
    )
    await db_session.commit()
    await db_session.refresh(user)

    sent = {}

    async def fake_send_email(to: str, subject: str, html_body: str) -> bool:
        sent["to"] = to
        sent["subject"] = subject
        return True

    import app.routers.support_requests as sr

    monkeypatch.setattr(sr, "send_email", fake_send_email)

    created = await client.post(
        "/api/v1/support-requests",
        json={"subject": "Printer", "message": "Out of toner"},
        headers=auth_headers(user),
    )
    req_id = created.json()["id"]

    resp = await client.post(
        f"/api/v1/support-requests/{req_id}/email", headers=auth_headers(user)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["sent"] is True
    assert body["support_email"] == "help@acme.com"
    assert sent["to"] == "help@acme.com"
    assert "Printer" in sent["subject"]
