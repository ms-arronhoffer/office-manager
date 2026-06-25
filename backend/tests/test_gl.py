import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lease import Lease
from tests.conftest import auth_headers


@pytest_asyncio.fixture
async def accounting_lease(db_session: AsyncSession) -> Lease:
    lease = Lease(
        id=uuid.uuid4(),
        organization_id=None,
        lease_name="GL Test Lease",
        expiration_year=2027,
        lease_commencement_date=date(2026, 1, 1),
        lease_expiration=date(2027, 1, 1),
        accounting_standard="asc842",
        lease_classification="operating",
        payment_amount=Decimal("1000"),
        payment_frequency="monthly",
        incremental_borrowing_rate=Decimal("0.05"),
        currency="USD",
    )
    db_session.add(lease)
    await db_session.commit()
    await db_session.refresh(lease)
    return lease


@pytest.mark.asyncio
async def test_list_accounts_seeds_defaults(client, accountant_user):
    resp = await client.get("/api/v1/gl/accounts", headers=auth_headers(accountant_user))
    assert resp.status_code == 200
    accounts = resp.json()
    assert len(accounts) >= 9
    codes = {a["code"] for a in accounts}
    assert "1000" in codes  # Cash
    assert "2000" in codes  # Lease Liability


@pytest.mark.asyncio
async def test_viewer_cannot_access_gl(client, viewer_user):
    resp = await client.get("/api/v1/gl/accounts", headers=auth_headers(viewer_user))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_account_and_duplicate(client, accountant_user):
    headers = auth_headers(accountant_user)
    resp = await client.post(
        "/api/v1/gl/accounts",
        headers=headers,
        json={"code": "9000", "name": "Misc Expense", "type": "expense"},
    )
    assert resp.status_code == 201
    assert resp.json()["normal_balance"] == "debit"

    # Duplicate code is rejected.
    dup = await client.post(
        "/api/v1/gl/accounts",
        headers=headers,
        json={"code": "9000", "name": "Other", "type": "expense"},
    )
    assert dup.status_code == 409

    # Invalid type rejected.
    bad = await client.post(
        "/api/v1/gl/accounts",
        headers=headers,
        json={"code": "9100", "name": "Bad", "type": "nonsense"},
    )
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_manual_journal_entry_balanced(client, accountant_user):
    headers = auth_headers(accountant_user)
    accounts = (await client.get("/api/v1/gl/accounts", headers=headers)).json()
    by_code = {a["code"]: a for a in accounts}
    cash = by_code["1000"]["id"]
    income = by_code["4000"]["id"]

    resp = await client.post(
        "/api/v1/gl/journal-entries",
        headers=headers,
        json={
            "entry_date": "2026-03-15",
            "memo": "Rent received",
            "lines": [
                {"account_id": cash, "debit": "1000", "credit": "0"},
                {"account_id": income, "debit": "0", "credit": "1000"},
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "posted"
    assert len(body["lines"]) == 2


@pytest.mark.asyncio
async def test_unbalanced_journal_entry_rejected(client, accountant_user):
    headers = auth_headers(accountant_user)
    accounts = (await client.get("/api/v1/gl/accounts", headers=headers)).json()
    by_code = {a["code"]: a for a in accounts}
    cash = by_code["1000"]["id"]
    income = by_code["4000"]["id"]

    resp = await client.post(
        "/api/v1/gl/journal-entries",
        headers=headers,
        json={
            "entry_date": "2026-03-15",
            "lines": [
                {"account_id": cash, "debit": "1000", "credit": "0"},
                {"account_id": income, "debit": "0", "credit": "900"},
            ],
        },
    )
    assert resp.status_code == 422
    assert "unbalanced" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_period_close_blocks_posting(client, accountant_user):
    headers = auth_headers(accountant_user)
    accounts = (await client.get("/api/v1/gl/accounts", headers=headers)).json()
    by_code = {a["code"]: a for a in accounts}
    cash = by_code["1000"]["id"]
    income = by_code["4000"]["id"]

    # Close March 2026.
    close = await client.post("/api/v1/gl/periods/2026/3/close", headers=headers)
    assert close.status_code == 200
    assert close.json()["status"] == "closed"

    # Posting into a closed period is blocked.
    resp = await client.post(
        "/api/v1/gl/journal-entries",
        headers=headers,
        json={
            "entry_date": "2026-03-20",
            "lines": [
                {"account_id": cash, "debit": "10", "credit": "0"},
                {"account_id": income, "debit": "0", "credit": "10"},
            ],
        },
    )
    assert resp.status_code == 422
    assert "closed" in resp.json()["detail"].lower()

    # Reopen and posting succeeds.
    reopen = await client.post("/api/v1/gl/periods/2026/3/reopen", headers=headers)
    assert reopen.status_code == 200
    ok = await client.post(
        "/api/v1/gl/journal-entries",
        headers=headers,
        json={
            "entry_date": "2026-03-20",
            "lines": [
                {"account_id": cash, "debit": "10", "credit": "0"},
                {"account_id": income, "debit": "0", "credit": "10"},
            ],
        },
    )
    assert ok.status_code == 201


@pytest.mark.asyncio
async def test_post_lease_and_trial_balance(client, accountant_user, accounting_lease):
    headers = auth_headers(accountant_user)
    resp = await client.post(
        f"/api/v1/gl/journal-entries/post-lease/{accounting_lease.id}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    entries = resp.json()
    assert len(entries) > 0
    # Each posted entry is balanced.
    for entry in entries:
        debit = sum(Decimal(l["debit"]) for l in entry["lines"])
        credit = sum(Decimal(l["credit"]) for l in entry["lines"])
        assert debit == credit

    # Trial balance nets to zero (debits == credits).
    tb = (await client.get("/api/v1/gl/trial-balance", headers=headers)).json()
    total_debit = sum(Decimal(r["debit"]) for r in tb)
    total_credit = sum(Decimal(r["credit"]) for r in tb)
    assert total_debit == total_credit


@pytest.mark.asyncio
async def test_export_csv(client, accountant_user, accounting_lease):
    headers = auth_headers(accountant_user)
    await client.post(
        f"/api/v1/gl/journal-entries/post-lease/{accounting_lease.id}",
        headers=headers,
    )
    resp = await client.get("/api/v1/gl/export", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    text = resp.text
    assert text.splitlines()[0] == "Date,Journal No.,Account,Debit,Credit,Memo"
    assert len(text.splitlines()) > 1
