"""Tests for the Budgeting module (Phase 1.4)."""

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.general_ledger import GLAccount
from app.services import budget_service, gl_service
from tests.conftest import auth_headers


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def accounts(db_session: AsyncSession) -> dict[str, GLAccount]:
    await gl_service.seed_default_accounts(db_session, None)
    rows = (
        await db_session.execute(
            select(GLAccount).where(GLAccount.organization_id.is_(None))
        )
    ).scalars().all()
    return {a.code: a for a in rows}


# ─── Service unit tests ──────────────────────────────────────────────────────

def test_fiscal_year_bounds_clamps_as_of():
    start, end = budget_service.fiscal_year_bounds(2025)
    assert start == date(2025, 1, 1) and end == date(2025, 12, 31)
    _, clamped = budget_service.fiscal_year_bounds(2025, date(2025, 6, 30))
    assert clamped == date(2025, 6, 30)
    # as_of outside the year is ignored.
    _, ignored = budget_service.fiscal_year_bounds(2025, date(2030, 1, 1))
    assert ignored == date(2025, 12, 31)


@pytest.mark.asyncio
async def test_actuals_sum_on_normal_side(db_session, accounts):
    # Post an expense of 400 (Dr expense / Cr cash) in 2025.
    await gl_service.create_journal_entry(
        db_session,
        None,
        entry_date=date(2025, 3, 1),
        lines=[
            {"account_id": accounts["6000"].id, "debit": Decimal("400"), "credit": 0},
            {"account_id": accounts["1000"].id, "debit": 0, "credit": Decimal("400")},
        ],
    )
    actuals = await budget_service.actuals_by_account(
        db_session, None, date(2025, 1, 1), date(2025, 12, 31)
    )
    # Expense (debit-normal) actual is +400.
    assert actuals[accounts["6000"].id] == Decimal("400.00")
    # Cash (debit-normal) reduced by 400 => -400.
    assert actuals[accounts["1000"].id] == Decimal("-400.00")


# ─── API tests ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_viewer_cannot_access_budgets(client, viewer_user):
    resp = await client.get("/api/v1/budgets", headers=auth_headers(viewer_user))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_and_list_budget(client, accountant_user, accounts):
    headers = auth_headers(accountant_user)
    resp = await client.post(
        "/api/v1/budgets",
        headers=headers,
        json={
            "name": "FY2025 Operating",
            "fiscal_year": 2025,
            "lines": [
                {"account_id": str(accounts["6000"].id), "amount": "5000"},
                {"account_id": str(accounts["4000"].id), "amount": "20000"},
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["fiscal_year"] == 2025
    assert Decimal(body["total_amount"]) == Decimal("25000.00")
    assert len(body["lines"]) == 2

    listed = await client.get("/api/v1/budgets?fiscal_year=2025", headers=headers)
    assert len(listed.json()) == 1


@pytest.mark.asyncio
async def test_duplicate_account_rejected(client, accountant_user, accounts):
    headers = auth_headers(accountant_user)
    resp = await client.post(
        "/api/v1/budgets",
        headers=headers,
        json={
            "name": "Dup",
            "fiscal_year": 2025,
            "lines": [
                {"account_id": str(accounts["6000"].id), "amount": "1"},
                {"account_id": str(accounts["6000"].id), "amount": "2"},
            ],
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_duplicate_name_conflict(client, accountant_user, accounts):
    headers = auth_headers(accountant_user)
    payload = {"name": "FY2025", "fiscal_year": 2025, "lines": []}
    first = await client.post("/api/v1/budgets", headers=headers, json=payload)
    assert first.status_code == 201
    second = await client.post("/api/v1/budgets", headers=headers, json=payload)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_budget_vs_actual_report(client, accountant_user, accounts, db_session):
    headers = auth_headers(accountant_user)
    # Budget 5000 of expense; actual 400.
    budget = (
        await client.post(
            "/api/v1/budgets",
            headers=headers,
            json={
                "name": "FY2025 Variance",
                "fiscal_year": 2025,
                "lines": [{"account_id": str(accounts["6000"].id), "amount": "5000"}],
            },
        )
    ).json()
    await gl_service.create_journal_entry(
        db_session,
        None,
        entry_date=date(2025, 4, 1),
        lines=[
            {"account_id": accounts["6000"].id, "debit": Decimal("400"), "credit": 0},
            {"account_id": accounts["1000"].id, "debit": 0, "credit": Decimal("400")},
        ],
    )
    resp = await client.get(f"/api/v1/budgets/{budget['id']}/report", headers=headers)
    assert resp.status_code == 200, resp.text
    report = resp.json()
    row = report["rows"][0]
    assert Decimal(row["budget"]) == Decimal("5000.00")
    assert Decimal(row["actual"]) == Decimal("400.00")
    assert Decimal(row["variance"]) == Decimal("-4600.00")
    assert Decimal(report["total_variance"]) == Decimal("-4600.00")


@pytest.mark.asyncio
async def test_update_budget_lines(client, accountant_user, accounts):
    headers = auth_headers(accountant_user)
    budget = (
        await client.post(
            "/api/v1/budgets",
            headers=headers,
            json={"name": "Editable", "fiscal_year": 2026, "lines": []},
        )
    ).json()
    resp = await client.patch(
        f"/api/v1/budgets/{budget['id']}",
        headers=headers,
        json={
            "status": "active",
            "lines": [{"account_id": str(accounts["6000"].id), "amount": "1000"}],
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "active"
    assert Decimal(resp.json()["total_amount"]) == Decimal("1000.00")


@pytest.mark.asyncio
async def test_delete_budget(client, accountant_user, accounts):
    headers = auth_headers(accountant_user)
    budget = (
        await client.post(
            "/api/v1/budgets",
            headers=headers,
            json={"name": "Temp", "fiscal_year": 2027, "lines": []},
        )
    ).json()
    resp = await client.delete(f"/api/v1/budgets/{budget['id']}", headers=headers)
    assert resp.status_code == 204
    missing = await client.get(f"/api/v1/budgets/{budget['id']}", headers=headers)
    assert missing.status_code == 404
