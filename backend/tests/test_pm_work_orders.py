"""Tests for the preventive-maintenance work-order automation engine."""
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.models.maintenance import MaintenanceTask
from app.models.maintenance_ticket import MaintenanceTicket
from app.services.pm_service import (
    PM_CATEGORY_NAME,
    generate_due_work_orders,
    task_is_due_for_generation,
)
from tests.conftest import auth_headers


# ── Schema exposure ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_task_exposes_automation_fields(client, admin_user):
    resp = await client.post(
        "/api/v1/maintenance/tasks",
        headers=auth_headers(admin_user),
        json={
            "category": "elevators_lifts",
            "title": "State elevator certification",
            "frequency": "annual",
            "next_due_date": "2030-01-15",
            "is_regulatory": True,
            "auto_generate_work_order": True,
            "work_order_lead_days": 30,
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["auto_generate_work_order"] is True
    assert data["work_order_lead_days"] == 30
    assert data["last_generated_due_date"] is None


# ── due-detection unit logic ──────────────────────────────────────────────────

def _task(**kw) -> MaintenanceTask:
    base = dict(
        category="hvac",
        title="t",
        status="scheduled",
        auto_generate_work_order=True,
        work_order_lead_days=7,
        next_due_date=date(2030, 1, 10),
        last_generated_due_date=None,
        is_regulatory=False,
    )
    base.update(kw)
    return MaintenanceTask(**base)


def test_due_detection_respects_lead_window():
    task = _task(next_due_date=date(2030, 1, 10), work_order_lead_days=7)
    # Before the window opens.
    assert task_is_due_for_generation(task, date(2030, 1, 2)) is False
    # Inside the window.
    assert task_is_due_for_generation(task, date(2030, 1, 3)) is True
    assert task_is_due_for_generation(task, date(2030, 1, 10)) is True


def test_due_detection_skips_disabled_completed_and_already_generated():
    today = date(2030, 1, 5)
    assert task_is_due_for_generation(_task(auto_generate_work_order=False), today) is False
    assert task_is_due_for_generation(_task(status="completed"), today) is False
    assert task_is_due_for_generation(_task(next_due_date=None), today) is False
    already = _task(last_generated_due_date=date(2030, 1, 10))
    assert task_is_due_for_generation(already, today) is False


# ── service generation ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_due_work_orders_creates_ticket(db_session, admin_user, sample_office):
    task = MaintenanceTask(
        category="fire_life_safety",
        title="Sprinkler inspection",
        office_id=sample_office.id,
        status="scheduled",
        auto_generate_work_order=True,
        work_order_lead_days=14,
        next_due_date=date.today() + timedelta(days=5),
        is_regulatory=True,
    )
    db_session.add(task)
    await db_session.commit()

    created = await generate_due_work_orders(db_session)
    await db_session.commit()

    assert len(created) == 1
    ticket = created[0]
    assert ticket.source_task_id == task.id
    assert ticket.office_id == sample_office.id
    assert ticket.priority == "high"  # regulatory → high
    assert ticket.subject.startswith("PM: ")

    # The PM category was auto-created.
    from app.models.maintenance_ticket import TicketCategory

    pm_cat = (
        await db_session.execute(
            select(TicketCategory).where(TicketCategory.name == PM_CATEGORY_NAME)
        )
    ).scalar_one()
    assert ticket.category_id == pm_cat.id

    # Dedup: a second run for the same due cycle creates nothing.
    again = await generate_due_work_orders(db_session)
    await db_session.commit()
    assert again == []

    # The task records the generated cycle.
    refreshed = (
        await db_session.execute(
            select(MaintenanceTask).where(MaintenanceTask.id == task.id)
        )
    ).scalar_one()
    assert refreshed.last_generated_due_date == task.next_due_date


@pytest.mark.asyncio
async def test_generate_skips_task_without_office(db_session, admin_user):
    task = MaintenanceTask(
        category="hvac",
        title="No office task",
        office_id=None,
        status="scheduled",
        auto_generate_work_order=True,
        work_order_lead_days=0,
        next_due_date=date.today(),
    )
    db_session.add(task)
    await db_session.commit()

    created = await generate_due_work_orders(db_session)
    await db_session.commit()
    assert created == []


# ── manual generate endpoint ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_manual_generate_endpoint(client, admin_user, sample_office):
    create = await client.post(
        "/api/v1/maintenance/tasks",
        headers=auth_headers(admin_user),
        json={
            "category": "hvac",
            "title": "Quarterly filter change",
            "office_id": str(sample_office.id),
            "frequency": "quarterly",
            "next_due_date": str(date.today() + timedelta(days=3)),
            "auto_generate_work_order": True,
            "work_order_lead_days": 10,
        },
    )
    task_id = create.json()["id"]

    resp = await client.post(
        f"/api/v1/maintenance/tasks/{task_id}/generate-work-order",
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["created"] is True
    assert body["ticket_id"]

    # Second call is a no-op (already generated for the cycle).
    resp2 = await client.post(
        f"/api/v1/maintenance/tasks/{task_id}/generate-work-order",
        headers=auth_headers(admin_user),
    )
    assert resp2.status_code == 201, resp2.text
    assert resp2.json()["created"] is False


@pytest.mark.asyncio
async def test_manual_generate_requires_due_date(client, admin_user):
    create = await client.post(
        "/api/v1/maintenance/tasks",
        headers=auth_headers(admin_user),
        json={"category": "hvac", "title": "No due date"},
    )
    task_id = create.json()["id"]
    resp = await client.post(
        f"/api/v1/maintenance/tasks/{task_id}/generate-work-order",
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 422, resp.text


# ── compliance endpoint ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_compliance_metrics(client, admin_user, sample_office):
    today = date.today()
    # An overdue regulatory task.
    await client.post(
        "/api/v1/maintenance/tasks",
        headers=auth_headers(admin_user),
        json={
            "category": "fire_life_safety",
            "title": "Overdue sprinkler",
            "office_id": str(sample_office.id),
            "next_due_date": str(today - timedelta(days=5)),
            "is_regulatory": True,
        },
    )
    # An on-time, non-regulatory task with automation on.
    await client.post(
        "/api/v1/maintenance/tasks",
        headers=auth_headers(admin_user),
        json={
            "category": "hvac",
            "title": "Upcoming filter change",
            "office_id": str(sample_office.id),
            "next_due_date": str(today + timedelta(days=20)),
            "auto_generate_work_order": True,
        },
    )

    resp = await client.get(
        "/api/v1/maintenance/compliance", headers=auth_headers(admin_user)
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["active_tasks"] == 2
    assert data["overdue"] == 1
    assert data["on_time"] == 1
    assert data["regulatory_active"] == 1
    assert data["regulatory_overdue"] == 1
    assert data["automation_enabled"] == 1
    assert data["on_time_rate"] == 50.0
    assert data["regulatory_on_time_rate"] == 0.0
    fls = next(c for c in data["by_category"] if c["category"] == "fire_life_safety")
    assert fls["regulatory_overdue"] == 1
