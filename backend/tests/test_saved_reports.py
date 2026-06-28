"""Tests for saved & scheduled reports and the NL report builder (Item 4)."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.auth.jwt_handler import create_access_token
from app.auth.password import hash_password
from app.models.office import Office
from app.models.organization import Organization
from app.models.saved_report import ReportSchedule, SavedReport
from app.models.user import User
from app.services import ai_service
from app.tasks import scheduled_reports


async def _make_org_user(db_session, plan: str, email: str, role: str = "admin") -> tuple[dict, Organization]:
    org = Organization(name=f"Org {plan}", slug=f"org-{plan}-{email[:4]}", plan=plan)
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    user = User(
        email=email,
        display_name="U",
        password_hash=hash_password("x"),
        auth_provider="internal",
        role=role,
        is_active=True,
        organization_id=org.id,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    headers = {"Authorization": "Bearer " + create_access_token({"sub": str(user.id), "role": user.role})}
    return headers, org


# ── Saved report CRUD ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_saved_report_validates_columns(client, db_session):
    headers, _ = await _make_org_user(db_session, "pro", "sr1@test.com")
    # Unknown column is rejected.
    resp = await client.post(
        "/api/v1/saved-reports",
        headers=headers,
        json={"name": "bad", "dataset": "offices", "columns": ["office_number", "not_a_column"], "format": "pdf"},
    )
    assert resp.status_code == 400, resp.text

    # Valid spec is accepted and cleaned.
    resp = await client.post(
        "/api/v1/saved-reports",
        headers=headers,
        json={
            "name": "Active offices",
            "dataset": "offices",
            "columns": ["office_number", "city"],
            "filters": {"is_active": "true"},
            "format": "csv",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["dataset"] == "offices"
    assert data["filters"] == {"is_active": True}


@pytest.mark.asyncio
async def test_saved_report_unknown_dataset_rejected(client, db_session):
    headers, _ = await _make_org_user(db_session, "pro", "sr2@test.com")
    resp = await client.post(
        "/api/v1/saved-reports",
        headers=headers,
        json={"name": "x", "dataset": "nope", "format": "pdf"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_saved_report_list_is_org_scoped(client, db_session):
    headers_a, _ = await _make_org_user(db_session, "pro", "orga@test.com")
    headers_b, _ = await _make_org_user(db_session, "pro", "orgb@test.com")
    await client.post(
        "/api/v1/saved-reports",
        headers=headers_a,
        json={"name": "A report", "dataset": "offices", "format": "csv"},
    )
    # Org B sees none of org A's reports.
    resp = await client.get("/api/v1/saved-reports", headers=headers_b)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_schedule_crud_and_next_run(client, db_session):
    headers, _ = await _make_org_user(db_session, "pro", "sched@test.com")
    rep = await client.post(
        "/api/v1/saved-reports",
        headers=headers,
        json={"name": "Offices", "dataset": "offices", "format": "csv"},
    )
    report_id = rep.json()["id"]

    # Recipients are required.
    bad = await client.post(
        f"/api/v1/saved-reports/{report_id}/schedules",
        headers=headers,
        json={"frequency": "daily", "recipients": []},
    )
    assert bad.status_code == 400

    ok = await client.post(
        f"/api/v1/saved-reports/{report_id}/schedules",
        headers=headers,
        json={"frequency": "weekly", "day_of_week": 0, "recipients": ["a@x.com"]},
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["next_run_at"] is not None

    listed = await client.get(f"/api/v1/saved-reports/{report_id}/schedules", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1


# ── Scheduled-report delivery task ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_scheduled_reports_renders_and_emails(db_session, monkeypatch):
    _, org = await _make_org_user(db_session, "pro", "deliver@test.com")
    db_session.add(Office(
        office_number=900, region_number=1, location_type="office",
        location_name="HQ", city="Seattle", is_active=True,
        organization_id=org.id,
    ))
    report = SavedReport(
        organization_id=org.id, name="Offices", dataset="offices",
        columns=["office_number", "city"], format="csv",
    )
    db_session.add(report)
    await db_session.commit()
    await db_session.refresh(report)

    schedule = ReportSchedule(
        organization_id=org.id, saved_report_id=report.id, frequency="daily",
        recipients=["ops@example.com"], is_active=True,
        next_run_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db_session.add(schedule)
    await db_session.commit()
    schedule_id = schedule.id

    sent: list[str] = []

    async def fake_send(to, subject, html_body, attachment_bytes, attachment_filename, attachment_content_type="application/pdf"):
        sent.append(to)
        assert attachment_bytes  # rendered something
        return True

    monkeypatch.setattr(scheduled_reports, "send_email_with_attachment", fake_send)

    await scheduled_reports.send_scheduled_reports()

    assert sent == ["ops@example.com"]
    refreshed = await db_session.get(ReportSchedule, schedule_id)
    await db_session.refresh(refreshed)
    assert refreshed.last_run_at is not None
    assert refreshed.next_run_at > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_send_scheduled_reports_skips_future_and_inactive(db_session, monkeypatch):
    _, org = await _make_org_user(db_session, "pro", "skip@test.com")
    report = SavedReport(organization_id=org.id, name="R", dataset="offices", format="csv")
    db_session.add(report)
    await db_session.commit()
    await db_session.refresh(report)
    db_session.add_all([
        ReportSchedule(
            organization_id=org.id, saved_report_id=report.id, frequency="daily",
            recipients=["a@x.com"], is_active=False,
            next_run_at=datetime.now(timezone.utc) - timedelta(hours=1),
        ),
        ReportSchedule(
            organization_id=org.id, saved_report_id=report.id, frequency="daily",
            recipients=["b@x.com"], is_active=True,
            next_run_at=datetime.now(timezone.utc) + timedelta(days=1),
        ),
    ])
    await db_session.commit()

    sent: list[str] = []

    async def fake_send(*args, **kwargs):
        sent.append(kwargs.get("to") or args[0])
        return True

    monkeypatch.setattr(scheduled_reports, "send_email_with_attachment", fake_send)
    await scheduled_reports.send_scheduled_reports()
    assert sent == []


# ── NL report builder (AI) ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_report_build_maps_prompt_and_drops_invalid(client, db_session, monkeypatch):
    headers, _ = await _make_org_user(db_session, "pro", "build@test.com")

    async def fake_build(prompt, datasets):
        # Model returns a valid dataset plus one invalid column and one bad filter.
        return {
            "dataset": "leases",
            "columns": ["lease_name", "made_up_column"],
            "filters": {"expiration_year": "2026", "ghost_filter": "x"},
        }

    monkeypatch.setattr(ai_service, "build_report_spec", fake_build)
    resp = await client.post(
        "/api/v1/ai/reports/build", headers=headers, json={"prompt": "leases expiring in 2026"}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["dataset"] == "leases"
    assert data["columns"] == ["lease_name"]
    assert data["filters"] == {"expiration_year": 2026}


@pytest.mark.asyncio
async def test_report_build_unknown_dataset_returns_422(client, db_session, monkeypatch):
    headers, _ = await _make_org_user(db_session, "pro", "build422@test.com")

    async def fake_build(prompt, datasets):
        return {"dataset": "totally_unknown", "columns": [], "filters": {}}

    monkeypatch.setattr(ai_service, "build_report_spec", fake_build)
    resp = await client.post(
        "/api/v1/ai/reports/build", headers=headers, json={"prompt": "x"}
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_report_build_gated_for_starter(client, db_session):
    headers, _ = await _make_org_user(db_session, "starter", "buildstarter@test.com")
    resp = await client.post(
        "/api/v1/ai/reports/build", headers=headers, json={"prompt": "x"}
    )
    assert resp.status_code == 402


@pytest.mark.asyncio
async def test_report_build_degrades_when_unconfigured(client, db_session, monkeypatch):
    headers, _ = await _make_org_user(db_session, "pro", "builddegraded@test.com")

    async def fake_build(prompt, datasets):
        raise ai_service.AIUnavailableError("AI assist is not configured.")

    monkeypatch.setattr(ai_service, "build_report_spec", fake_build)
    resp = await client.post(
        "/api/v1/ai/reports/build", headers=headers, json={"prompt": "x"}
    )
    assert resp.status_code == 503
