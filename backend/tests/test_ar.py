import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer_invoice import (
    Customer,
    CustomerInvoice,
    CustomerInvoiceLine,
    CustomerReceipt,
)
from app.models.general_ledger import GLAccount, JournalEntry, JournalEntryLine
from app.services import ar_service, gl_service
from tests.conftest import auth_headers


# ─── Pure service-layer unit tests ───────────────────────────────────────────

def _invoice(lines, receipts=(), due_date=None, invoice_date=date(2026, 1, 1)):
    inv = CustomerInvoice(
        id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        invoice_date=invoice_date,
        due_date=due_date,
        status="finalized",
    )
    inv.lines = [
        CustomerInvoiceLine(account_id=uuid.uuid4(), line_number=i + 1, amount=Decimal(a))
        for i, a in enumerate(lines)
    ]
    inv.receipts = [
        CustomerReceipt(invoice_id=inv.id, receipt_date=date(2026, 1, 2), amount=Decimal(a))
        for a in receipts
    ]
    return inv


def test_invoice_total_sums_lines():
    inv = _invoice(["100.00", "250.50"])
    assert ar_service.invoice_total(inv) == Decimal("350.50")


def test_amount_received_and_balance():
    inv = _invoice(["1000"], receipts=["300", "200"])
    assert ar_service.amount_received(inv) == Decimal("500.00")
    assert ar_service.balance_due(inv) == Decimal("500.00")


def test_balance_due_never_negative():
    inv = _invoice(["100"], receipts=["150"])
    assert ar_service.balance_due(inv) == Decimal("0.00")


def test_receipt_state_transitions():
    assert ar_service.receipt_state(_invoice(["100"])) == "open"
    assert ar_service.receipt_state(_invoice(["100"], receipts=["40"])) == "partial"
    assert ar_service.receipt_state(_invoice(["100"], receipts=["100"])) == "paid"
    assert ar_service.receipt_state(_invoice(["100"], receipts=["60", "40"])) == "paid"


def test_validate_currency_usd_only():
    assert ar_service.validate_currency("usd") == "USD"
    assert ar_service.validate_currency(None) == "USD"
    with pytest.raises(ar_service.ARError):
        ar_service.validate_currency("EUR")


def test_validate_lines_requires_positive_amounts():
    with pytest.raises(ar_service.ARError):
        ar_service.validate_lines([])
    with pytest.raises(ar_service.ARError):
        ar_service.validate_lines([{"account_id": uuid.uuid4(), "amount": Decimal("0")}])
    ar_service.validate_lines([{"account_id": uuid.uuid4(), "amount": Decimal("5")}])


def test_aging_bucket_mapping():
    assert ar_service._bucket_for(-5) == "current"
    assert ar_service._bucket_for(0) == "current"
    assert ar_service._bucket_for(15) == "1_30"
    assert ar_service._bucket_for(45) == "31_60"
    assert ar_service._bucket_for(75) == "61_90"
    assert ar_service._bucket_for(120) == "90_plus"


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def revenue_account(db_session: AsyncSession) -> GLAccount:
    """Seed the default chart of accounts and return a revenue account."""
    await gl_service.seed_default_accounts(db_session, None)
    acct = (
        await db_session.execute(
            select(GLAccount).where(
                GLAccount.organization_id.is_(None),
                GLAccount.code == "4000",
            )
        )
    ).scalar_one()
    return acct


@pytest_asyncio.fixture
async def customer(db_session: AsyncSession) -> Customer:
    c = Customer(id=uuid.uuid4(), organization_id=None, name="Tenant LLC")
    db_session.add(c)
    await db_session.commit()
    await db_session.refresh(c)
    return c


async def _create_invoice(client, headers, customer, account, amount="500.00", due_date=None):
    return await client.post(
        "/api/v1/ar/invoices",
        headers=headers,
        json={
            "customer_id": str(customer.id),
            "invoice_date": "2026-02-01",
            "due_date": due_date,
            "invoice_number": "INV-1",
            "lines": [{"account_id": str(account.id), "amount": amount, "description": "Rent"}],
        },
    )


# ─── API tests ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_viewer_cannot_access_ar(client, viewer_user):
    resp = await client.get("/api/v1/ar/invoices", headers=auth_headers(viewer_user))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_customer(client, accountant_user):
    headers = auth_headers(accountant_user)
    resp = await client.post(
        "/api/v1/ar/customers",
        headers=headers,
        json={"name": "Acme Tenant", "contact_email": "billing@acme.test"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["name"] == "Acme Tenant"


@pytest.mark.asyncio
async def test_create_invoice_draft(client, accountant_user, customer, revenue_account):
    headers = auth_headers(accountant_user)
    resp = await _create_invoice(client, headers, customer, revenue_account)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "draft"
    assert Decimal(body["total_amount"]) == Decimal("500.00")
    assert Decimal(body["balance_due"]) == Decimal("500.00")
    assert body["receipt_state"] == "open"
    assert body["journal_entry_id"] is None
    assert len(body["lines"]) == 1


@pytest.mark.asyncio
async def test_create_invoice_rejects_non_usd(client, accountant_user, customer, revenue_account):
    headers = auth_headers(accountant_user)
    resp = await client.post(
        "/api/v1/ar/invoices",
        headers=headers,
        json={
            "customer_id": str(customer.id),
            "invoice_date": "2026-02-01",
            "currency": "EUR",
            "lines": [{"account_id": str(revenue_account.id), "amount": "10"}],
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_invoice_rejects_unknown_account(client, accountant_user, customer, revenue_account):
    headers = auth_headers(accountant_user)
    resp = await client.post(
        "/api/v1/ar/invoices",
        headers=headers,
        json={
            "customer_id": str(customer.id),
            "invoice_date": "2026-02-01",
            "lines": [{"account_id": str(uuid.uuid4()), "amount": "10"}],
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_draft_invoice(client, accountant_user, customer, revenue_account):
    headers = auth_headers(accountant_user)
    created = (await _create_invoice(client, headers, customer, revenue_account)).json()
    resp = await client.patch(
        f"/api/v1/ar/invoices/{created['id']}",
        headers=headers,
        json={"lines": [{"account_id": str(revenue_account.id), "amount": "750"}]},
    )
    assert resp.status_code == 200, resp.text
    assert Decimal(resp.json()["total_amount"]) == Decimal("750.00")


@pytest.mark.asyncio
async def test_finalize_posts_balanced_entry(
    client, accountant_user, customer, revenue_account, db_session
):
    headers = auth_headers(accountant_user)
    created = (await _create_invoice(client, headers, customer, revenue_account)).json()
    resp = await client.post(f"/api/v1/ar/invoices/{created['id']}/finalize", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "finalized"
    assert body["journal_entry_id"] is not None

    entry = (
        await db_session.execute(
            select(JournalEntry).where(JournalEntry.id == uuid.UUID(body["journal_entry_id"]))
        )
    ).scalar_one()
    lines = (
        await db_session.execute(
            select(JournalEntryLine).where(JournalEntryLine.entry_id == entry.id)
        )
    ).scalars().all()
    total_debit = sum(l.debit for l in lines)
    total_credit = sum(l.credit for l in lines)
    assert total_debit == total_credit == Decimal("500.00")
    assert entry.source == "ar"
    # Debit lands on Accounts Receivable.
    ar_acct = (
        await db_session.execute(
            select(GLAccount).where(
                GLAccount.organization_id.is_(None), GLAccount.name == "Accounts Receivable"
            )
        )
    ).scalar_one()
    debit_line = next(l for l in lines if l.debit > 0)
    assert debit_line.account_id == ar_acct.id


@pytest.mark.asyncio
async def test_finalized_invoice_cannot_be_edited_or_deleted(
    client, accountant_user, customer, revenue_account
):
    headers = auth_headers(accountant_user)
    created = (await _create_invoice(client, headers, customer, revenue_account)).json()
    await client.post(f"/api/v1/ar/invoices/{created['id']}/finalize", headers=headers)

    patched = await client.patch(
        f"/api/v1/ar/invoices/{created['id']}",
        headers=headers,
        json={"memo": "nope"},
    )
    assert patched.status_code == 409
    deleted = await client.delete(f"/api/v1/ar/invoices/{created['id']}", headers=headers)
    assert deleted.status_code == 409


@pytest.mark.asyncio
async def test_receipt_flow_and_state(
    client, accountant_user, customer, revenue_account, db_session
):
    headers = auth_headers(accountant_user)
    created = (await _create_invoice(client, headers, customer, revenue_account)).json()
    await client.post(f"/api/v1/ar/invoices/{created['id']}/finalize", headers=headers)

    resp = await client.post(
        f"/api/v1/ar/invoices/{created['id']}/receipts",
        headers=headers,
        json={"receipt_date": "2026-02-15", "amount": "200", "method": "check"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["receipt_state"] == "partial"
    assert Decimal(body["amount_received"]) == Decimal("200.00")
    assert Decimal(body["balance_due"]) == Decimal("300.00")
    receipt_id = body["receipts"][0]["id"]

    pay_je = (
        await db_session.execute(
            select(JournalEntry).where(
                JournalEntry.source == "ar", JournalEntry.source_ref == f"receipt:{receipt_id}"
            )
        )
    ).scalar_one()
    pay_lines = (
        await db_session.execute(
            select(JournalEntryLine).where(JournalEntryLine.entry_id == pay_je.id)
        )
    ).scalars().all()
    assert sum(l.debit for l in pay_lines) == sum(l.credit for l in pay_lines) == Decimal("200.00")

    # Full receipt flips state to paid.
    resp = await client.post(
        f"/api/v1/ar/invoices/{created['id']}/receipts",
        headers=headers,
        json={"receipt_date": "2026-02-16", "amount": "300"},
    )
    assert resp.json()["receipt_state"] == "paid"


@pytest.mark.asyncio
async def test_receipt_cannot_exceed_balance(client, accountant_user, customer, revenue_account):
    headers = auth_headers(accountant_user)
    created = (await _create_invoice(client, headers, customer, revenue_account)).json()
    await client.post(f"/api/v1/ar/invoices/{created['id']}/finalize", headers=headers)
    resp = await client.post(
        f"/api/v1/ar/invoices/{created['id']}/receipts",
        headers=headers,
        json={"receipt_date": "2026-02-15", "amount": "600"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_delete_receipt_reverses_entry(
    client, accountant_user, customer, revenue_account, db_session
):
    headers = auth_headers(accountant_user)
    created = (await _create_invoice(client, headers, customer, revenue_account)).json()
    await client.post(f"/api/v1/ar/invoices/{created['id']}/finalize", headers=headers)
    paid = (await client.post(
        f"/api/v1/ar/invoices/{created['id']}/receipts",
        headers=headers,
        json={"receipt_date": "2026-02-15", "amount": "200"},
    )).json()
    receipt_id = paid["receipts"][0]["id"]

    resp = await client.delete(f"/api/v1/ar/receipts/{receipt_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    assert Decimal(resp.json()["balance_due"]) == Decimal("500.00")
    assert resp.json()["receipt_state"] == "open"

    remaining = (
        await db_session.execute(
            select(JournalEntry).where(
                JournalEntry.source == "ar", JournalEntry.source_ref == f"receipt:{receipt_id}"
            )
        )
    ).scalars().all()
    assert remaining == []


@pytest.mark.asyncio
async def test_void_finalized_invoice(client, accountant_user, customer, revenue_account, db_session):
    headers = auth_headers(accountant_user)
    created = (await _create_invoice(client, headers, customer, revenue_account)).json()
    await client.post(f"/api/v1/ar/invoices/{created['id']}/finalize", headers=headers)
    resp = await client.post(f"/api/v1/ar/invoices/{created['id']}/void", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "void"
    remaining = (
        await db_session.execute(
            select(JournalEntry).where(
                JournalEntry.source == "ar", JournalEntry.source_ref == f"invoice:{created['id']}"
            )
        )
    ).scalars().all()
    assert remaining == []


@pytest.mark.asyncio
async def test_aging_report_buckets(client, accountant_user, customer, revenue_account):
    headers = auth_headers(accountant_user)
    # Overdue invoice due well in the past.
    overdue = (await _create_invoice(
        client, headers, customer, revenue_account, amount="400", due_date="2026-01-01"
    )).json()
    await client.post(f"/api/v1/ar/invoices/{overdue['id']}/finalize", headers=headers)

    resp = await client.get("/api/v1/ar/aging?as_of=2026-03-15", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert Decimal(data["grand_total"]) == Decimal("400.00")
    # 2026-01-01 due, as-of 2026-03-15 => ~73 days past due => 61_90 bucket.
    assert Decimal(data["totals"]["61_90"]) == Decimal("400.00")
    assert len(data["customers"]) == 1
    assert Decimal(data["customers"][0]["total"]) == Decimal("400.00")


@pytest.mark.asyncio
async def test_open_only_invoice_filter(client, accountant_user, customer, revenue_account):
    headers = auth_headers(accountant_user)
    inv = (await _create_invoice(client, headers, customer, revenue_account)).json()
    # Draft invoice should not appear as open.
    resp = await client.get("/api/v1/ar/invoices?open_only=true", headers=headers)
    assert resp.json() == []
    await client.post(f"/api/v1/ar/invoices/{inv['id']}/finalize", headers=headers)
    resp = await client.get("/api/v1/ar/invoices?open_only=true", headers=headers)
    assert len(resp.json()) == 1
