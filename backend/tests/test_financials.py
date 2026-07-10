import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.general_ledger import GLAccount
from app.services import financials_service as fin
from app.services import gl_service
from tests.conftest import auth_headers


# ─── Pure period-helper unit tests ────────────────────────────────────────────

def test_period_bounds_month():
    assert fin.period_bounds(2026, 2) == (date(2026, 2, 1), date(2026, 2, 28))


def test_period_bounds_year_only():
    assert fin.period_bounds(2026, None) == (date(2026, 1, 1), date(2026, 12, 31))


def test_period_bounds_unbounded():
    assert fin.period_bounds(None, None) == (None, None)


def test_period_bounds_rejects_bad_month():
    with pytest.raises(ValueError):
        fin.period_bounds(2026, 13)


def test_as_of_date():
    assert fin.as_of_date(2026, 2) == date(2026, 2, 28)
    assert fin.as_of_date(2026, None) == date(2026, 12, 31)
    assert fin.as_of_date(None, None) is None


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def accounts(db_session: AsyncSession) -> dict[str, GLAccount]:
    """Seed the default chart of accounts and return a name→account map."""
    await gl_service.seed_default_accounts(db_session, None)
    rows = (
        await db_session.execute(
            select(GLAccount).where(GLAccount.organization_id.is_(None))
        )
    ).scalars().all()
    return {a.name: a for a in rows}


async def _post(db_session, accounts, entry_date, debit_name, credit_name, amount):
    await gl_service.create_journal_entry(
        db_session,
        None,
        entry_date=entry_date,
        lines=[
            {"account_id": accounts[debit_name].id, "debit": amount, "credit": 0},
            {"account_id": accounts[credit_name].id, "debit": 0, "credit": amount},
        ],
        source="manual",
    )


@pytest_asyncio.fixture
async def seeded_ledger(db_session: AsyncSession, accounts):
    """Post a small balanced set of entries spanning two months.

    - Jan: receive 1,000 cash as rental income; pay 400 cash operating cost.
    - Feb: pay 100 cash operating cost.
    """
    await _post(db_session, accounts, date(2026, 1, 5), "Cash", "Rental Income", Decimal("1000"))
    await _post(db_session, accounts, date(2026, 1, 20), "Operating Lease Cost", "Cash", Decimal("400"))
    await _post(db_session, accounts, date(2026, 2, 10), "Operating Lease Cost", "Cash", Decimal("100"))
    return accounts


# ─── Service-layer integration tests ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_income_statement_full_range(db_session, seeded_ledger):
    data = await fin.income_statement(db_session, None)
    assert data["total_revenue"] == Decimal("1000.00")
    assert data["total_expenses"] == Decimal("500.00")
    assert data["net_income"] == Decimal("500.00")
    assert {r["name"] for r in data["revenue"]} == {"Rental Income"}
    assert {r["name"] for r in data["expenses"]} == {"Operating Lease Cost"}


@pytest.mark.asyncio
async def test_income_statement_single_month(db_session, seeded_ledger):
    data = await fin.income_statement(db_session, None, year=2026, month=1)
    assert data["total_revenue"] == Decimal("1000.00")
    assert data["total_expenses"] == Decimal("400.00")
    assert data["net_income"] == Decimal("600.00")
    assert data["start_date"] == date(2026, 1, 1)
    assert data["end_date"] == date(2026, 1, 31)


@pytest.mark.asyncio
async def test_balance_sheet_balances(db_session, seeded_ledger):
    data = await fin.balance_sheet(db_session, None)
    # Cash = 1000 - 400 - 100 = 500.
    assert data["total_assets"] == Decimal("500.00")
    # No real liabilities/equity postings, but net income is folded into equity.
    assert data["net_income"] == Decimal("500.00")
    assert data["total_equity"] == Decimal("500.00")
    assert data["liabilities_and_equity"] == Decimal("500.00")
    assert data["balanced"] is True
    # The synthetic net-income equity line is present.
    assert any(r["name"] == "Net income (current period)" for r in data["equity"])


@pytest.mark.asyncio
async def test_balance_sheet_as_of_cutoff(db_session, seeded_ledger):
    # As of end of January, the February 100 expense/cash payment is excluded.
    data = await fin.balance_sheet(db_session, None, year=2026, month=1)
    assert data["as_of_date"] == date(2026, 1, 31)
    assert data["total_assets"] == Decimal("600.00")
    assert data["net_income"] == Decimal("600.00")
    assert data["balanced"] is True


@pytest.mark.asyncio
async def test_cash_flow_statement_full_range(db_session, seeded_ledger):
    data = await fin.cash_flow_statement(db_session, None)
    # Operating: +1000 rental income received, -400 -100 operating cost paid.
    assert data["operating"]["total"] == Decimal("500.00")
    assert data["investing"]["total"] == Decimal("0.00")
    assert data["financing"]["total"] == Decimal("0.00")
    assert data["net_change_in_cash"] == Decimal("500.00")
    assert data["beginning_cash"] == Decimal("0.00")
    assert data["ending_cash"] == Decimal("500.00")
    # Reconciles to the balance sheet cash line.
    bs = await fin.balance_sheet(db_session, None)
    assert data["ending_cash"] == bs["total_assets"]


@pytest.mark.asyncio
async def test_cash_flow_statement_single_month_carries_beginning(db_session, seeded_ledger):
    # February only: just the 100 operating-cost cash payment.
    data = await fin.cash_flow_statement(db_session, None, year=2026, month=2)
    assert data["start_date"] == date(2026, 2, 1)
    assert data["end_date"] == date(2026, 2, 28)
    # January's net +600 cash is the opening balance for February.
    assert data["beginning_cash"] == Decimal("600.00")
    assert data["net_change_in_cash"] == Decimal("-100.00")
    assert data["ending_cash"] == Decimal("500.00")
    assert data["operating"]["total"] == Decimal("-100.00")


@pytest.mark.asyncio
async def test_cash_flow_statement_classifies_financing_and_investing(db_session, accounts):
    # A non-cash entry (no cash movement) must be excluded entirely...
    await _post(
        db_session, accounts, date(2026, 3, 1),
        "Right-of-Use Asset", "Lease Liability", Decimal("5000"),
    )
    # ...a cash purchase of an asset is investing (use of cash)...
    await _post(
        db_session, accounts, date(2026, 3, 2),
        "Right-of-Use Asset", "Cash", Decimal("300"),
    )
    # ...and repaying the lease liability with cash is financing (use of cash).
    await _post(
        db_session, accounts, date(2026, 3, 3),
        "Lease Liability", "Cash", Decimal("200"),
    )
    data = await fin.cash_flow_statement(db_session, None)
    assert data["operating"]["total"] == Decimal("0.00")
    assert data["investing"]["total"] == Decimal("-300.00")
    assert data["financing"]["total"] == Decimal("-200.00")
    assert data["net_change_in_cash"] == Decimal("-500.00")
    assert data["ending_cash"] == Decimal("-500.00")
    # The non-cash recognition entry produced no cash-flow lines.
    assert all(
        r["name"] != "Right-of-Use Asset" or r["amount"] != Decimal("5000.00")
        for r in data["investing"]["lines"]
    )


# ─── API tests ───────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_viewer_cannot_access_financials(client, viewer_user):
    resp = await client.get(
        "/api/v1/financials/balance-sheet", headers=auth_headers(viewer_user)
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_income_statement_endpoint(client, accountant_user, seeded_ledger):
    resp = await client.get(
        "/api/v1/financials/income-statement", headers=auth_headers(accountant_user)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert Decimal(body["total_revenue"]) == Decimal("1000.00")
    assert Decimal(body["net_income"]) == Decimal("500.00")


@pytest.mark.asyncio
async def test_balance_sheet_endpoint(client, accountant_user, seeded_ledger):
    resp = await client.get(
        "/api/v1/financials/balance-sheet", headers=auth_headers(accountant_user)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["balanced"] is True
    assert Decimal(body["total_assets"]) == Decimal("500.00")


@pytest.mark.asyncio
async def test_balance_sheet_rejects_bad_month(client, accountant_user):
    resp = await client.get(
        "/api/v1/financials/balance-sheet",
        headers=auth_headers(accountant_user),
        params={"year": 2026, "month": 13},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_cash_flow_statement_endpoint(client, accountant_user, seeded_ledger):
    resp = await client.get(
        "/api/v1/financials/cash-flow-statement", headers=auth_headers(accountant_user)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert Decimal(body["net_change_in_cash"]) == Decimal("500.00")
    assert Decimal(body["ending_cash"]) == Decimal("500.00")
    assert Decimal(body["operating"]["total"]) == Decimal("500.00")


@pytest.mark.asyncio
async def test_viewer_cannot_access_cash_flow_statement(client, viewer_user):
    resp = await client.get(
        "/api/v1/financials/cash-flow-statement", headers=auth_headers(viewer_user)
    )
    assert resp.status_code == 403


# ─── PDF export tests ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_income_statement_pdf(client, accountant_user, seeded_ledger):
    resp = await client.get(
        "/api/v1/financials/income-statement/pdf", headers=auth_headers(accountant_user)
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_balance_sheet_pdf(client, accountant_user, seeded_ledger):
    resp = await client.get(
        "/api/v1/financials/balance-sheet/pdf", headers=auth_headers(accountant_user)
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_cash_flow_statement_pdf(client, accountant_user, seeded_ledger):
    resp = await client.get(
        "/api/v1/financials/cash-flow-statement/pdf", headers=auth_headers(accountant_user)
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_viewer_cannot_access_income_statement_pdf(client, viewer_user):
    resp = await client.get(
        "/api/v1/financials/income-statement/pdf", headers=auth_headers(viewer_user)
    )
    assert resp.status_code == 403
