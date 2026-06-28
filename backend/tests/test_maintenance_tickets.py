import pytest
from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_create_ticket(client, editor_user, sample_office, sample_category):
    resp = await client.post("/api/v1/maintenance-tickets", headers=auth_headers(editor_user), json={
        "subject": "Broken pipe",
        "priority": "high",
        "category_id": str(sample_category.id),
        "office_id": str(sample_office.id),
        "description": "Water leaking in room 101",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["subject"] == "Broken pipe"
    assert data["status"] == "open"


@pytest.mark.asyncio
async def test_list_tickets_with_status_filter(client, editor_user, sample_office, sample_category):
    # Create a ticket
    await client.post("/api/v1/maintenance-tickets", headers=auth_headers(editor_user), json={
        "subject": "Test ticket",
        "priority": "low",
        "category_id": str(sample_category.id),
        "office_id": str(sample_office.id),
        "description": "Test",
    })

    # Filter by status
    resp = await client.get(
        "/api/v1/maintenance-tickets?status=open",
        headers=auth_headers(editor_user),
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 1

    resp = await client.get(
        "/api/v1/maintenance-tickets?status=closed",
        headers=auth_headers(editor_user),
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_update_ticket(client, editor_user, sample_office, sample_category):
    create_resp = await client.post("/api/v1/maintenance-tickets", headers=auth_headers(editor_user), json={
        "subject": "Fix door",
        "priority": "medium",
        "category_id": str(sample_category.id),
        "office_id": str(sample_office.id),
        "description": "Door won't close",
    })
    ticket_id = create_resp.json()["id"]

    resp = await client.put(
        f"/api/v1/maintenance-tickets/{ticket_id}",
        headers=auth_headers(editor_user),
        json={"status": "in_progress"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"


@pytest.mark.asyncio
async def test_viewer_cannot_create_ticket(client, viewer_user, sample_office, sample_category):
    resp = await client.post("/api/v1/maintenance-tickets", headers=auth_headers(viewer_user), json={
        "subject": "No access",
        "priority": "low",
        "category_id": str(sample_category.id),
        "office_id": str(sample_office.id),
        "description": "Should fail",
    })
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_ticket_admin_only(client, editor_user, admin_user, sample_office, sample_category):
    create_resp = await client.post("/api/v1/maintenance-tickets", headers=auth_headers(editor_user), json={
        "subject": "Delete me",
        "priority": "low",
        "category_id": str(sample_category.id),
        "office_id": str(sample_office.id),
        "description": "Test delete",
    })
    ticket_id = create_resp.json()["id"]

    # Editor cannot delete
    resp = await client.delete(
        f"/api/v1/maintenance-tickets/{ticket_id}",
        headers=auth_headers(editor_user),
    )
    assert resp.status_code == 403

    # Admin can delete
    resp = await client.delete(
        f"/api/v1/maintenance-tickets/{ticket_id}",
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_create_ticket_succeeds_when_notification_side_effect_fails(
    client, editor_user, sample_office, sample_category, monkeypatch
):
    """A failing best-effort side-effect must not turn a committed ticket into a 500.

    Notifications/activity-log are best-effort and roll the session back on
    failure, which expires the freshly created ORM instance. Serializing the
    response must therefore happen before those side-effects, otherwise the
    create returns a spurious 500 ("failed to submit") even though the ticket
    was already committed.
    """
    import app.routers.maintenance_tickets as tickets_router

    async def _boom(*args, **kwargs):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(tickets_router, "send_ticket_created_emails", _boom)
    monkeypatch.setattr(tickets_router, "send_high_priority_ticket_emails", _boom)

    resp = await client.post(
        "/api/v1/maintenance-tickets",
        headers=auth_headers(editor_user),
        json={
            "subject": "Portal submitted ticket",
            "priority": "high",
            "category_id": str(sample_category.id),
            "office_id": str(sample_office.id),
            "description": "Submitted from the self-service portal",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["subject"] == "Portal submitted ticket"

    # And the ticket really is queryable afterwards (it was committed).
    listing = await client.get(
        "/api/v1/maintenance-tickets?status=open",
        headers=auth_headers(editor_user),
    )
    assert listing.status_code == 200
    assert any(t["id"] == data["id"] for t in listing.json()["items"])
