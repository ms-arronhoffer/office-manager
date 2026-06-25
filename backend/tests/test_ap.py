import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.general_ledger import GLAccount, JournalEntry, JournalEntryLine
from app.models.vendor import Vendor
from app.models.vendor_bill import VendorBill, VendorBillLine, VendorPayment
from app.services import ap_service, gl_service
from tests.conftest import auth_headers


# ─── Pure service-layer unit tests ───────────────────────────────────────────

def _bill(lines, payments=()):
    bill = VendorBill(
        id=uuid.uuid4(),
        vendor_id=uuid.uuid4(),
        bill_date=date(2026, 1, 1),
        status="finalized",
    )
    bill.lines = [
        VendorBillLine(account_id=uuid.uuid4(), line_number=i + 1, amount=Decimal(a))
        for i, a in enumerate(lines)
    ]
    bill.payments = [
        VendorPayment(bill_id=bill.id, payment_date=date(2026, 1, 2), amount=Decimal(a))
        for a in payments
    ]
    return bill


def test_bill_total_sums_lines():
    bill = _bill(["100.00", "250.50"])
    assert ap_service.bill_total(bill) == Decimal("350.50")


def test_amount_paid_and_balance():
    bill = _bill(["1000"], payments=["300", "200"])
    assert ap_service.amount_paid(bill) == Decimal("500.00")
    assert ap_service.balance_due(bill) == Decimal("500.00")


def test_balance_due_never_negative():
    bill = _bill(["100"], payments=["150"])
    assert ap_service.balance_due(bill) == Decimal("0.00")


def test_payment_state_transitions():
    assert ap_service.payment_state(_bill(["100"])) == "open"
    assert ap_service.payment_state(_bill(["100"], payments=["40"])) == "partial"
    assert ap_service.payment_state(_bill(["100"], payments=["100"])) == "paid"
    assert ap_service.payment_state(_bill(["100"], payments=["60", "40"])) == "paid"


def test_validate_currency_usd_only():
    assert ap_service.validate_currency("usd") == "USD"
    assert ap_service.validate_currency(None) == "USD"
    with pytest.raises(ap_service.APError):
        ap_service.validate_currency("EUR")


def test_validate_lines_requires_positive_amounts():
    with pytest.raises(ap_service.APError):
        ap_service.validate_lines([])
    with pytest.raises(ap_service.APError):
        ap_service.validate_lines([{"account_id": uuid.uuid4(), "amount": Decimal("0")}])
    # Valid line does not raise.
    ap_service.validate_lines([{"account_id": uuid.uuid4(), "amount": Decimal("5")}])


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def expense_account(db_session: AsyncSession) -> GLAccount:
    """Seed the default chart of accounts and return an expense account."""
    await gl_service.seed_default_accounts(db_session, None)
    acct = (
        await db_session.execute(
            select(GLAccount).where(
                GLAccount.organization_id.is_(None),
                GLAccount.code == "6000",
            )
        )
    ).scalar_one()
    return acct


@pytest_asyncio.fixture
async def vendor(db_session: AsyncSession) -> Vendor:
    v = Vendor(id=uuid.uuid4(), organization_id=None, company_name="Acme Services")
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)
    return v


async def _create_bill(client, headers, vendor, account, amount="500.00"):
    return await client.post(
        "/api/v1/ap/bills",
        headers=headers,
        json={
            "vendor_id": str(vendor.id),
            "bill_date": "2026-02-01",
            "bill_number": "INV-1",
            "lines": [{"account_id": str(account.id), "amount": amount, "description": "Repairs"}],
        },
    )


# ─── API tests ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_viewer_cannot_access_ap(client, viewer_user):
    resp = await client.get("/api/v1/ap/bills", headers=auth_headers(viewer_user))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_bill_draft(client, accountant_user, vendor, expense_account):
    headers = auth_headers(accountant_user)
    resp = await _create_bill(client, headers, vendor, expense_account)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "draft"
    assert Decimal(body["total_amount"]) == Decimal("500.00")
    assert Decimal(body["balance_due"]) == Decimal("500.00")
    assert body["payment_state"] == "open"
    assert body["journal_entry_id"] is None
    assert len(body["lines"]) == 1


@pytest.mark.asyncio
async def test_create_bill_rejects_non_usd(client, accountant_user, vendor, expense_account):
    headers = auth_headers(accountant_user)
    resp = await client.post(
        "/api/v1/ap/bills",
        headers=headers,
        json={
            "vendor_id": str(vendor.id),
            "bill_date": "2026-02-01",
            "currency": "EUR",
            "lines": [{"account_id": str(expense_account.id), "amount": "10"}],
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_bill_rejects_unknown_account(client, accountant_user, vendor, expense_account):
    headers = auth_headers(accountant_user)
    resp = await client.post(
        "/api/v1/ap/bills",
        headers=headers,
        json={
            "vendor_id": str(vendor.id),
            "bill_date": "2026-02-01",
            "lines": [{"account_id": str(uuid.uuid4()), "amount": "10"}],
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_draft_bill(client, accountant_user, vendor, expense_account):
    headers = auth_headers(accountant_user)
    created = (await _create_bill(client, headers, vendor, expense_account)).json()
    resp = await client.patch(
        f"/api/v1/ap/bills/{created['id']}",
        headers=headers,
        json={"lines": [{"account_id": str(expense_account.id), "amount": "750"}]},
    )
    assert resp.status_code == 200, resp.text
    assert Decimal(resp.json()["total_amount"]) == Decimal("750.00")


@pytest.mark.asyncio
async def test_finalize_posts_balanced_entry(
    client, accountant_user, vendor, expense_account, db_session
):
    headers = auth_headers(accountant_user)
    created = (await _create_bill(client, headers, vendor, expense_account)).json()
    resp = await client.post(f"/api/v1/ap/bills/{created['id']}/finalize", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "finalized"
    assert body["journal_entry_id"] is not None

    # GL entry is balanced: Dr expense 500 / Cr Accounts Payable 500.
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
    assert entry.source == "ap"


@pytest.mark.asyncio
async def test_finalized_bill_cannot_be_edited_or_deleted(
    client, accountant_user, vendor, expense_account
):
    headers = auth_headers(accountant_user)
    created = (await _create_bill(client, headers, vendor, expense_account)).json()
    await client.post(f"/api/v1/ap/bills/{created['id']}/finalize", headers=headers)

    patched = await client.patch(
        f"/api/v1/ap/bills/{created['id']}",
        headers=headers,
        json={"memo": "nope"},
    )
    assert patched.status_code == 409
    deleted = await client.delete(f"/api/v1/ap/bills/{created['id']}", headers=headers)
    assert deleted.status_code == 409


@pytest.mark.asyncio
async def test_payment_flow_and_state(
    client, accountant_user, vendor, expense_account, db_session
):
    headers = auth_headers(accountant_user)
    created = (await _create_bill(client, headers, vendor, expense_account)).json()
    await client.post(f"/api/v1/ap/bills/{created['id']}/finalize", headers=headers)

    # Partial payment.
    resp = await client.post(
        f"/api/v1/ap/bills/{created['id']}/payments",
        headers=headers,
        json={"payment_date": "2026-02-15", "amount": "200", "method": "check"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["payment_state"] == "partial"
    assert Decimal(body["amount_paid"]) == Decimal("200.00")
    assert Decimal(body["balance_due"]) == Decimal("300.00")
    payment_id = body["payments"][0]["id"]

    # Payment posts a balanced Dr AP / Cr Cash entry.
    pay_je = (
        await db_session.execute(
            select(JournalEntry).where(JournalEntry.source == "ap", JournalEntry.source_ref == f"payment:{payment_id}")
        )
    ).scalar_one()
    pay_lines = (
        await db_session.execute(
            select(JournalEntryLine).where(JournalEntryLine.entry_id == pay_je.id)
        )
    ).scalars().all()
    assert sum(l.debit for l in pay_lines) == sum(l.credit for l in pay_lines) == Decimal("200.00")

    # Pay the remainder -> paid.
    resp = await client.post(
        f"/api/v1/ap/bills/{created['id']}/payments",
        headers=headers,
        json={"payment_date": "2026-02-20", "amount": "300"},
    )
    assert resp.json()["payment_state"] == "paid"


@pytest.mark.asyncio
async def test_payment_cannot_exceed_balance(client, accountant_user, vendor, expense_account):
    headers = auth_headers(accountant_user)
    created = (await _create_bill(client, headers, vendor, expense_account)).json()
    await client.post(f"/api/v1/ap/bills/{created['id']}/finalize", headers=headers)
    resp = await client.post(
        f"/api/v1/ap/bills/{created['id']}/payments",
        headers=headers,
        json={"payment_date": "2026-02-15", "amount": "600"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_payment_requires_finalized_bill(client, accountant_user, vendor, expense_account):
    headers = auth_headers(accountant_user)
    created = (await _create_bill(client, headers, vendor, expense_account)).json()
    resp = await client.post(
        f"/api/v1/ap/bills/{created['id']}/payments",
        headers=headers,
        json={"payment_date": "2026-02-15", "amount": "100"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_delete_payment_reverses_state(
    client, accountant_user, vendor, expense_account, db_session
):
    headers = auth_headers(accountant_user)
    created = (await _create_bill(client, headers, vendor, expense_account)).json()
    await client.post(f"/api/v1/ap/bills/{created['id']}/finalize", headers=headers)
    pay = await client.post(
        f"/api/v1/ap/bills/{created['id']}/payments",
        headers=headers,
        json={"payment_date": "2026-02-15", "amount": "200"},
    )
    payment_id = pay.json()["payments"][0]["id"]

    resp = await client.delete(f"/api/v1/ap/payments/{payment_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["payment_state"] == "open"
    assert Decimal(body["amount_paid"]) == Decimal("0.00")

    # Payment GL entry was reversed.
    remaining = (
        await db_session.execute(
            select(JournalEntry).where(
                JournalEntry.source == "ap",
                JournalEntry.source_ref == f"payment:{payment_id}",
            )
        )
    ).scalars().all()
    assert remaining == []


@pytest.mark.asyncio
async def test_void_unpaid_bill_reverses_gl(
    client, accountant_user, vendor, expense_account, db_session
):
    headers = auth_headers(accountant_user)
    created = (await _create_bill(client, headers, vendor, expense_account)).json()
    await client.post(f"/api/v1/ap/bills/{created['id']}/finalize", headers=headers)

    resp = await client.post(f"/api/v1/ap/bills/{created['id']}/void", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "void"
    assert resp.json()["journal_entry_id"] is None

    remaining = (
        await db_session.execute(
            select(JournalEntry).where(
                JournalEntry.source == "ap",
                JournalEntry.source_ref == f"bill:{created['id']}",
            )
        )
    ).scalars().all()
    assert remaining == []


@pytest.mark.asyncio
async def test_void_paid_bill_blocked(client, accountant_user, vendor, expense_account):
    headers = auth_headers(accountant_user)
    created = (await _create_bill(client, headers, vendor, expense_account)).json()
    await client.post(f"/api/v1/ap/bills/{created['id']}/finalize", headers=headers)
    await client.post(
        f"/api/v1/ap/bills/{created['id']}/payments",
        headers=headers,
        json={"payment_date": "2026-02-15", "amount": "100"},
    )
    resp = await client.post(f"/api/v1/ap/bills/{created['id']}/void", headers=headers)
    assert resp.status_code == 409
