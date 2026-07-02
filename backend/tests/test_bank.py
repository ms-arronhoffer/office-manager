import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bank_account import BankAccount, BankReconciliation, BankTransaction
from app.models.general_ledger import GLAccount
from app.services import bank_service, gl_service
from tests.conftest import auth_headers


# ─── Pure service-layer unit tests: statement parsing ────────────────────────

def test_parse_csv_amount_column():
    csv_text = "Date,Description,Amount\n2026-01-05,Rent deposit,1500.00\n2026-01-08,Utility payment,-120.50\n"
    txns, source = bank_service.parse_statement(csv_text.encode(), "stmt.csv")
    assert source == "csv"
    assert len(txns) == 2
    assert txns[0]["txn_date"] == date(2026, 1, 5)
    assert txns[0]["amount"] == Decimal("1500.00")
    assert txns[1]["amount"] == Decimal("-120.50")


def test_parse_csv_debit_credit_columns():
    csv_text = "Date,Memo,Debit,Credit\n01/05/2026,Deposit,,1000\n01/06/2026,Check,250.00,\n"
    txns, source = bank_service.parse_statement(csv_text, "stmt.csv")
    assert source == "csv"
    assert txns[0]["amount"] == Decimal("1000.00")
    # Debit reduces the balance (a withdrawal) -> negative signed amount.
    assert txns[1]["amount"] == Decimal("-250.00")


def test_parse_csv_parenthesized_negative():
    csv_text = "Date,Amount,Description\n2026-02-01,($75.25),Fee\n"
    txns, _ = bank_service.parse_statement(csv_text, "x.csv")
    assert txns[0]["amount"] == Decimal("-75.25")


def test_parse_csv_requires_date_column():
    with pytest.raises(bank_service.BankError):
        bank_service.parse_statement("Foo,Bar\n1,2\n", "x.csv")


def test_parse_ofx_statement():
    ofx = """OFXHEADER:100
    <OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKTRANLIST>
    <STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260115120000<TRNAMT>2000.00<FITID>A1<NAME>Client Payment</STMTTRN>
    <STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260116<TRNAMT>-45.00<FITID>A2<NAME>Bank Fee<MEMO>Monthly</STMTTRN>
    </BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>"""
    txns, source = bank_service.parse_statement(ofx, "stmt.qfx")
    assert source == "ofx"
    assert len(txns) == 2
    assert txns[0]["fitid"] == "A1"
    assert txns[0]["txn_date"] == date(2026, 1, 15)
    assert txns[0]["amount"] == Decimal("2000.00")
    assert txns[1]["description"] == "Bank Fee Monthly"
    assert txns[1]["amount"] == Decimal("-45.00")


# ─── Pure service-layer unit tests: reconciliation math ──────────────────────

def _recon(begin, end, amounts):
    r = BankReconciliation(
        id=uuid.uuid4(),
        bank_account_id=uuid.uuid4(),
        statement_date=date(2026, 1, 31),
        beginning_balance=Decimal(begin),
        ending_balance=Decimal(end),
    )
    r.transactions = [
        BankTransaction(
            id=uuid.uuid4(),
            bank_account_id=r.bank_account_id,
            txn_date=date(2026, 1, 10),
            amount=Decimal(a),
        )
        for a in amounts
    ]
    return r


def test_cleared_totals_and_balance():
    r = _recon("1000", "1850", ["1000", "-150"])
    assert bank_service.cleared_deposits(r) == Decimal("1000.00")
    assert bank_service.cleared_withdrawals(r) == Decimal("150.00")
    assert bank_service.cleared_balance(r) == Decimal("1850.00")
    assert bank_service.difference(r) == Decimal("0.00")
    assert bank_service.is_balanced(r) is True


def test_difference_when_out_of_balance():
    r = _recon("1000", "2000", ["500"])
    assert bank_service.cleared_balance(r) == Decimal("1500.00")
    assert bank_service.difference(r) == Decimal("500.00")
    assert bank_service.is_balanced(r) is False


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def cash_account(db_session: AsyncSession) -> GLAccount:
    await gl_service.seed_default_accounts(db_session, None)
    return (
        await db_session.execute(
            select(GLAccount).where(
                GLAccount.organization_id.is_(None), GLAccount.code == "1000"
            )
        )
    ).scalar_one()


@pytest_asyncio.fixture
async def bank_account(db_session: AsyncSession, cash_account: GLAccount) -> BankAccount:
    acct = BankAccount(
        id=uuid.uuid4(),
        organization_id=None,
        name="Operating Checking",
        gl_account_id=cash_account.id,
    )
    db_session.add(acct)
    await db_session.commit()
    await db_session.refresh(acct)
    return acct


# ─── API tests ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_viewer_cannot_access_bank(client, viewer_user):
    resp = await client.get("/api/v1/bank/accounts", headers=auth_headers(viewer_user))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_account_requires_asset_gl(client, accountant_user, db_session):
    await gl_service.seed_default_accounts(db_session, None)
    revenue = (
        await db_session.execute(
            select(GLAccount).where(
                GLAccount.organization_id.is_(None), GLAccount.code == "4000"
            )
        )
    ).scalar_one()
    resp = await client.post(
        "/api/v1/bank/accounts",
        headers=auth_headers(accountant_user),
        json={"name": "Bad", "gl_account_id": str(revenue.id)},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_account(client, accountant_user, cash_account):
    resp = await client.post(
        "/api/v1/bank/accounts",
        headers=auth_headers(accountant_user),
        json={"name": "Operating Checking", "gl_account_id": str(cash_account.id)},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Operating Checking"
    assert body["gl_account_code"] == "1000"


@pytest.mark.asyncio
async def test_import_csv_is_idempotent_by_fitid(client, accountant_user, bank_account):
    ofx = (
        "<OFX><STMTTRN><DTPOSTED>20260105<TRNAMT>1500.00<FITID>F1<NAME>Deposit</STMTTRN>"
        "<STMTTRN><DTPOSTED>20260108<TRNAMT>-120.50<FITID>F2<NAME>Utility</STMTTRN></OFX>"
    )
    headers = auth_headers(accountant_user)
    files = {"file": ("stmt.ofx", ofx.encode(), "application/x-ofx")}
    resp = await client.post(
        f"/api/v1/bank/accounts/{bank_account.id}/import", headers=headers, files=files
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["imported"] == 2
    # Re-importing the same file skips both by FITID.
    files = {"file": ("stmt.ofx", ofx.encode(), "application/x-ofx")}
    resp = await client.post(
        f"/api/v1/bank/accounts/{bank_account.id}/import", headers=headers, files=files
    )
    assert resp.json()["imported"] == 0
    assert resp.json()["skipped"] == 2


@pytest.mark.asyncio
async def test_full_reconciliation_flow(client, accountant_user, bank_account):
    headers = auth_headers(accountant_user)
    # Import two transactions: +1000 deposit and -150 withdrawal.
    ofx = (
        "<OFX><STMTTRN><DTPOSTED>20260105<TRNAMT>1000.00<FITID>G1<NAME>Rent</STMTTRN>"
        "<STMTTRN><DTPOSTED>20260108<TRNAMT>-150.00<FITID>G2<NAME>Fee</STMTTRN></OFX>"
    )
    files = {"file": ("stmt.ofx", ofx.encode(), "application/x-ofx")}
    await client.post(
        f"/api/v1/bank/accounts/{bank_account.id}/import", headers=headers, files=files
    )
    txns = (
        await client.get(
            f"/api/v1/bank/accounts/{bank_account.id}/transactions", headers=headers
        )
    ).json()
    txn_ids = [t["id"] for t in txns]

    # Start a reconciliation: begin 1000, end 1850.
    recon = (
        await client.post(
            f"/api/v1/bank/accounts/{bank_account.id}/reconciliations",
            headers=headers,
            json={"statement_date": "2026-01-31", "beginning_balance": "1000.00", "ending_balance": "1850.00"},
        )
    ).json()
    recon_id = recon["id"]

    # Clear both transactions -> ties out.
    resp = await client.post(
        f"/api/v1/bank/reconciliations/{recon_id}/clear",
        headers=headers,
        json={"transaction_ids": txn_ids},
    )
    assert resp.status_code == 200, resp.text
    summary = resp.json()["summary"]
    assert summary["cleared_balance"] == "1850.00"
    assert summary["difference"] == "0.00"
    assert summary["is_balanced"] is True

    # Complete succeeds now.
    resp = await client.post(
        f"/api/v1/bank/reconciliations/{recon_id}/complete", headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_complete_blocked_when_unbalanced(client, accountant_user, bank_account):
    headers = auth_headers(accountant_user)
    recon = (
        await client.post(
            f"/api/v1/bank/accounts/{bank_account.id}/reconciliations",
            headers=headers,
            json={"statement_date": "2026-01-31", "beginning_balance": "0", "ending_balance": "500.00"},
        )
    ).json()
    resp = await client.post(
        f"/api/v1/bank/reconciliations/{recon['id']}/complete", headers=headers
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_beginning_balance_defaults_to_prior(client, accountant_user, bank_account):
    headers = auth_headers(accountant_user)
    # First reconciliation, completed with ending 750.
    r1 = (
        await client.post(
            f"/api/v1/bank/accounts/{bank_account.id}/reconciliations",
            headers=headers,
            json={"statement_date": "2026-01-31", "beginning_balance": "0", "ending_balance": "0"},
        )
    ).json()
    await client.post(f"/api/v1/bank/reconciliations/{r1['id']}/complete", headers=headers)

    # Manually add a +750 transaction and reconcile a second period without a
    # beginning balance -> it should default to the prior ending balance (0).
    r2 = (
        await client.post(
            f"/api/v1/bank/accounts/{bank_account.id}/reconciliations",
            headers=headers,
            json={"statement_date": "2026-02-28", "ending_balance": "0"},
        )
    ).json()
    assert r2["beginning_balance"] == "0.00"


@pytest.mark.asyncio
async def test_cleared_transaction_cannot_be_deleted(client, accountant_user, bank_account):
    headers = auth_headers(accountant_user)
    txn = (
        await client.post(
            f"/api/v1/bank/accounts/{bank_account.id}/transactions",
            headers=headers,
            json={"txn_date": "2026-01-05", "amount": "100.00", "description": "x"},
        )
    ).json()
    recon = (
        await client.post(
            f"/api/v1/bank/accounts/{bank_account.id}/reconciliations",
            headers=headers,
            json={"statement_date": "2026-01-31", "beginning_balance": "0", "ending_balance": "100.00"},
        )
    ).json()
    await client.post(
        f"/api/v1/bank/reconciliations/{recon['id']}/clear",
        headers=headers,
        json={"transaction_ids": [txn["id"]]},
    )
    resp = await client.delete(f"/api/v1/bank/transactions/{txn['id']}", headers=headers)
    assert resp.status_code == 409
