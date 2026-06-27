import pytest
from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_catalog_lists_six_categories(client, admin_user):
    resp = await client.get("/api/v1/maintenance/catalog", headers=auth_headers(admin_user))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    keys = {c["value"] for c in data["categories"]}
    assert keys == {
        "hvac",
        "fire_life_safety",
        "plumbing_backflow",
        "refuse_waste",
        "exterior_structural",
        "elevators_lifts",
    }
    assert "annual" in data["frequencies"]


@pytest.mark.asyncio
async def test_create_task_with_reminder(client, admin_user):
    resp = await client.post(
        "/api/v1/maintenance/tasks",
        headers=auth_headers(admin_user),
        json={
            "category": "fire_life_safety",
            "subtopic": "sprinkler_inspection",
            "title": "Annual sprinkler inspection",
            "frequency": "annual",
            "next_due_date": "2027-01-15",
            "is_regulatory": True,
            "reminder_enabled": True,
            "reminder_days_before": 30,
            "reminder_recipients": ["pm@example.com"],
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["category"] == "fire_life_safety"
    assert data["is_regulatory"] is True
    assert data["reminder_enabled"] is True
    assert data["reminder_days_before"] == 30
    assert data["reminder_recipients"] == ["pm@example.com"]


@pytest.mark.asyncio
async def test_create_task_rejects_invalid_subtopic(client, admin_user):
    resp = await client.post(
        "/api/v1/maintenance/tasks",
        headers=auth_headers(admin_user),
        json={"category": "hvac", "subtopic": "not_a_real_topic", "title": "x"},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_create_task_rejects_unknown_category(client, admin_user):
    resp = await client.post(
        "/api/v1/maintenance/tasks",
        headers=auth_headers(admin_user),
        json={"category": "spaceships", "title": "x"},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_list_tasks_filtered_by_category(client, admin_user):
    await client.post(
        "/api/v1/maintenance/tasks",
        headers=auth_headers(admin_user),
        json={"category": "plumbing_backflow", "title": "Backflow test"},
    )
    await client.post(
        "/api/v1/maintenance/tasks",
        headers=auth_headers(admin_user),
        json={"category": "elevators_lifts", "title": "Cab inspection"},
    )
    resp = await client.get(
        "/api/v1/maintenance/tasks",
        headers=auth_headers(admin_user),
        params={"category": "plumbing_backflow"},
    )
    assert resp.status_code == 200, resp.text
    titles = [t["title"] for t in resp.json()]
    assert titles == ["Backflow test"]


@pytest.mark.asyncio
async def test_logging_service_advances_next_due(client, admin_user):
    create = await client.post(
        "/api/v1/maintenance/tasks",
        headers=auth_headers(admin_user),
        json={
            "category": "exterior_structural",
            "subtopic": "roofing",
            "title": "Roof inspection",
            "frequency": "semi_annual",
        },
    )
    task_id = create.json()["id"]

    log = await client.post(
        "/api/v1/maintenance/logs",
        headers=auth_headers(admin_user),
        json={
            "task_id": task_id,
            "service_date": "2026-06-01",
            "description": "Cleared drains, checked flashing.",
        },
    )
    assert log.status_code == 201, log.text

    resp = await client.get(
        f"/api/v1/maintenance/tasks",
        headers=auth_headers(admin_user),
        params={"category": "exterior_structural"},
    )
    task = resp.json()[0]
    assert task["last_completed_date"] == "2026-06-01"
    # semi_annual == 182 days after 2026-06-01 -> 2026-11-30
    assert task["next_due_date"] == "2026-11-30"


@pytest.mark.asyncio
async def test_overview_counts_overdue_and_due_soon(client, admin_user):
    # An overdue task in the past.
    await client.post(
        "/api/v1/maintenance/tasks",
        headers=auth_headers(admin_user),
        json={"category": "hvac", "title": "Old filter change", "next_due_date": "2000-01-01"},
    )
    resp = await client.get("/api/v1/maintenance/overview", headers=auth_headers(admin_user))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total_tasks"] >= 1
    assert data["overdue"] >= 1
    hvac_stat = next(c for c in data["by_category"] if c["category"] == "hvac")
    assert hvac_stat["overdue"] >= 1


@pytest.mark.asyncio
async def test_create_asset_and_delete(client, admin_user):
    create = await client.post(
        "/api/v1/maintenance/assets",
        headers=auth_headers(admin_user),
        json={
            "category": "refuse_waste",
            "subtopic": "compactor_baler",
            "name": "Compactor A",
            "is_regulatory": False,
        },
    )
    assert create.status_code == 201, create.text
    asset_id = create.json()["id"]

    delete = await client.delete(
        f"/api/v1/maintenance/assets/{asset_id}", headers=auth_headers(admin_user)
    )
    assert delete.status_code == 204, delete.text


@pytest.mark.asyncio
async def test_viewer_cannot_create_task(client, viewer_user):
    resp = await client.post(
        "/api/v1/maintenance/tasks",
        headers=auth_headers(viewer_user),
        json={"category": "hvac", "title": "x"},
    )
    assert resp.status_code == 403, resp.text
