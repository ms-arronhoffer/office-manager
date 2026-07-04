"""Audit-grade, cross-cutting accounting validations.

Where the per-feature suites (``test_gl``/``test_ar``/``test_ap``/``test_cam``/
``test_rent``/``test_owners``/``test_financials``) verify each accounting
function in isolation, this suite exercises them *together* through the shared
general ledger and asserts the platform-wide invariants an auditor would test:

  * every posted journal entry balances and the ledger as a whole balances,
  * the financial statements cross-tie (equation, net income, cash),
  * subledger control accounts are only moved by their own posting sources,
  * postings are idempotent (re-posting never double-counts),
  * organization ledgers are isolated, and
  * the built-in auditor (``accounting_audit_service``) both *attests* a healthy
    ledger and *detects* every class of corruption it is designed to catch.
"""

import uuid
from datetime import date, datetime, timezone
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
from app.models.general_ledger import (
    GLAccount,
    JournalEntry,
    JournalEntryLine,
)
from app.models.lease import Lease
from app.models.organization import Organization
from app.models.owner import PropertyOwner
from app.models.vendor import Vendor
from app.models.vendor_bill import (
    VendorBill,
    VendorBillLine,
    VendorPayment,
)
from app.services import (
    accounting_audit_service as audit,
    ap_service,
    ar_service,
    cam_service,
    gl_service,
    owner_service,
    rent_service,
)
from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _accounts(db: AsyncSession, org=None) -> dict[str, GLAccount]:
    """Seed the full chart of accounts (defaults + every feature) and map by name."""
    await gl_service.seed_default_accounts(db, org)
    await gl_service.ensure_accounts(db, org, ar_service.AR_ACCOUNTS, commit=False)
    await gl_service.ensure_accounts(db, org, ap_service.AP_ACCOUNTS, commit=False)
    await gl_service.ensure_accounts(db, org, cam_service.CAM_ACCOUNTS, commit=False)
    await gl_service.ensure_accounts(db, org, rent_service.RENT_ACCOUNTS, commit=False)
    await owner_service.ensure_owner_accounts(db, org)
    await db.commit()
    rows = (
        await db.execute(select(GLAccount).where(GLAccount.organization_id == org))
    ).scalars().all()
    return {a.name: a for a in rows}


async def _org(db: AsyncSession) -> uuid.UUID:
    """Create a real organization row so org-scoped FKs are satisfiable."""
    org = Organization(id=uuid.uuid4(), name="Other Org", slug=f"org-{uuid.uuid4().hex[:8]}")
    db.add(org)
    await db.commit()
    return org.id


async def _raw_entry(db, org, accounts, *, entry_date, legs, source="manual",
                     status="posted"):
    """Persist a journal entry directly, bypassing service validation.

    ``legs`` is a list of ``(account_name, debit, credit)`` tuples. Used to inject
    deliberately malformed entries the auditor must catch.
    """
    period = await gl_service.get_or_create_period(
        db, org, entry_date.year, entry_date.month, commit=False
    )
    entry = JournalEntry(
        organization_id=org,
        period=period,
        entry_date=entry_date,
        source=source,
        status=status,
        posted_at=None if status != "posted" else datetime.now(timezone.utc),
    )
    for i, (name, debit, credit) in enumerate(legs, start=1):
        entry.lines.append(
            JournalEntryLine(
                account_id=accounts[name].id,
                line_number=i,
                debit=Decimal(str(debit)),
                credit=Decimal(str(credit)),
            )
        )
    db.add(entry)
    await db.commit()
    return entry


# ─── A rich, healthy multi-source ledger ───────────────────────────────────────

@pytest_asyncio.fixture
async def healthy_ledger(db_session: AsyncSession):
    """Post balanced entries from every accounting subsystem into one GL."""
    db = db_session
    accounts = await _accounts(db)

    # 1) Manual opening balance: seed cash against equity.
    await gl_service.create_journal_entry(
        db, None,
        entry_date=date(2026, 1, 1),
        lines=[
            {"account_id": accounts["Cash"].id, "debit": 50000, "credit": 0},
            {"account_id": accounts["Retained Earnings"].id, "debit": 0, "credit": 50000},
        ],
        source="manual",
    )

    # 2) Lease recognition (ASC 842): source="lease".
    lease = Lease(
        id=uuid.uuid4(), organization_id=None, lease_name="Suite 200",
        expiration_year=2027, lease_commencement_date=date(2026, 1, 1),
        lease_expiration=date(2027, 1, 1), accounting_standard="asc842",
        lease_classification="operating", payment_amount=Decimal("1000"),
        payment_frequency="monthly", incremental_borrowing_rate=Decimal("0.05"),
        currency="USD",
    )
    db.add(lease)
    await db.commit()
    await gl_service.post_lease_entries(db, None, lease)

    # 3) Accounts Receivable: finalize + post an invoice, then a partial receipt.
    customer = Customer(id=uuid.uuid4(), organization_id=None, name="Tenant LLC")
    db.add(customer)
    await db.commit()
    invoice = CustomerInvoice(
        id=uuid.uuid4(), organization_id=None, customer_id=customer.id,
        invoice_date=date(2026, 2, 1), status="finalized",
    )
    invoice.lines = [
        CustomerInvoiceLine(
            account_id=accounts["Service Revenue"].id, line_number=1,
            amount=Decimal("1200"),
        )
    ]
    db.add(invoice)
    await db.commit()
    await ar_service.post_invoice_to_gl(db, None, invoice)
    receipt = CustomerReceipt(
        id=uuid.uuid4(), organization_id=None, invoice_id=invoice.id,
        receipt_date=date(2026, 2, 15), amount=Decimal("500"),
    )
    db.add(receipt)
    await db.commit()
    await ar_service.post_receipt_to_gl(db, None, receipt)

    # 4) Accounts Payable: finalize + post a bill, then a payment.
    vendor = Vendor(id=uuid.uuid4(), organization_id=None, company_name="Maint Co")
    db.add(vendor)
    await db.commit()
    bill = VendorBill(
        id=uuid.uuid4(), organization_id=None, vendor_id=vendor.id,
        bill_date=date(2026, 2, 3),
        status="finalized", total_amount=Decimal("800"),
    )
    bill.lines = [
        VendorBillLine(
            account_id=accounts["Operating Lease Cost"].id, line_number=1,
            amount=Decimal("800"),
        )
    ]
    db.add(bill)
    await db.commit()
    await ap_service.post_bill_to_gl(db, None, bill)
    payment = VendorPayment(
        id=uuid.uuid4(), organization_id=None, bill_id=bill.id,
        payment_date=date(2026, 2, 20), amount=Decimal("800"),
    )
    db.add(payment)
    await db.commit()
    await ap_service.post_payment_to_gl(db, None, payment)

    # 5) Owner trust: record income then pay a distribution. source="owner".
    owner = PropertyOwner(
        id=uuid.uuid4(), organization_id=None, name="Owner Group",
        owner_type="company",
    )
    db.add(owner)
    await db.commit()
    await owner_service.record_ledger_entry(
        db, None, owner, entry_type="income", amount=Decimal("2000"),
        entry_date=date(2026, 2, 5),
    )
    await owner_service.record_ledger_entry(
        db, None, owner, entry_type="distribution", amount=Decimal("700"),
        entry_date=date(2026, 2, 25),
    )

    # 6) Security deposit liability. source="deposit".
    await gl_service.create_journal_entry(
        db, None,
        entry_date=date(2026, 2, 6),
        lines=[
            {"account_id": accounts["Cash"].id, "debit": 1500, "credit": 0},
            {"account_id": accounts["Security Deposits Held"].id, "debit": 0, "credit": 1500},
        ],
        source="deposit",
    )

    # 7) CAM reconciliation true-up. source="cam".
    await gl_service.create_journal_entry(
        db, None,
        entry_date=date(2026, 12, 31),
        lines=[
            {"account_id": accounts["CAM Receivable"].id, "debit": 300, "credit": 0},
            {"account_id": accounts["CAM Recovery Income"].id, "debit": 0, "credit": 300},
        ],
        source="cam",
    )

    return {"accounts": accounts, "invoice": invoice, "receipt": receipt}


# ─── Core invariant assertions on the healthy ledger ───────────────────────────

async def test_healthy_ledger_is_attested(db_session, healthy_ledger):
    report = await audit.run_audit(db_session, None)
    assert report["attested"] is True, report["checks"]
    assert report["checks_failed"] == 0
    assert report["checks_passed"] == report["checks_total"]
    assert report["entry_count"] > 0


async def test_trial_balance_ties_out(db_session, healthy_ledger):
    report = await audit.run_audit(db_session, None)
    assert report["total_debits"] == report["total_credits"]
    # Independently confirm via the trial-balance report.
    rows = await gl_service.trial_balance(db_session, None)
    debits = sum((r["debit"] for r in rows), Decimal("0"))
    credits = sum((r["credit"] for r in rows), Decimal("0"))
    assert debits == credits == report["total_debits"]


async def test_every_entry_balances(db_session, healthy_ledger):
    entries = (
        await db_session.execute(
            select(JournalEntry).where(JournalEntry.organization_id.is_(None))
        )
    ).scalars().unique().all()
    for entry in entries:
        legs = (
            await db_session.execute(
                select(JournalEntryLine).where(JournalEntryLine.entry_id == entry.id)
            )
        ).scalars().all()
        debit = sum((l.debit for l in legs), Decimal("0"))
        credit = sum((l.credit for l in legs), Decimal("0"))
        assert debit == credit, f"entry {entry.id} unbalanced"


async def test_statements_cross_tie(db_session, healthy_ledger):
    report = await audit.run_audit(db_session, None)
    by_key = {c["key"]: c for c in report["checks"]}
    assert by_key["accounting_equation"]["status"] == "pass"
    assert by_key["net_income_tie"]["status"] == "pass"
    assert by_key["cash_flow_tie"]["status"] == "pass"


async def test_control_accounts_clean(db_session, healthy_ledger):
    report = await audit.run_audit(db_session, None)
    control = next(c for c in report["checks"] if c["key"] == "control_account_integrity")
    assert control["status"] == "pass", control["findings"]
    codes = {c["code"] for c in report["control_accounts"]}
    # Every control account touched by the healthy ledger is attested.
    assert {"1100", "1050", "2200", "2300", "2500", "1200"} <= codes


async def test_reposting_is_idempotent(db_session, healthy_ledger):
    before = await audit.run_audit(db_session, None)
    # Re-post the same invoice and receipt; the ledger must not double-count.
    await ar_service.post_invoice_to_gl(db_session, None, healthy_ledger["invoice"])
    await ar_service.post_receipt_to_gl(db_session, None, healthy_ledger["receipt"])
    after = await audit.run_audit(db_session, None)
    assert after["total_debits"] == before["total_debits"]
    assert after["total_credits"] == before["total_credits"]
    assert after["entry_count"] == before["entry_count"]
    assert after["attested"] is True


async def test_ledger_is_organization_isolated(db_session, healthy_ledger):
    # A second org with its own out-of-balance entry must not affect org=None.
    other = await _org(db_session)
    other_accounts = await _accounts(db_session, other)
    await _raw_entry(
        db_session, other, other_accounts, entry_date=date(2026, 3, 1),
        legs=[("Cash", 10, 0), ("Rental Income", 0, 999)], source="manual",
    )
    report = await audit.run_audit(db_session, None)
    assert report["attested"] is True
    # The corrupt other-org ledger is independently detected as failing.
    other_report = await audit.run_audit(db_session, other)
    assert other_report["attested"] is False


# ─── Defect-injection: the auditor must catch every class of corruption ────────

async def test_detects_unbalanced_entry(db_session):
    accounts = await _accounts(db_session)
    await _raw_entry(
        db_session, None, accounts, entry_date=date(2026, 1, 5),
        legs=[("Cash", 100, 0), ("Rental Income", 0, 90)],
    )
    report = await audit.run_audit(db_session, None)
    assert report["attested"] is False
    by_key = {c["key"]: c for c in report["checks"]}
    assert by_key["journal_entry_balance"]["status"] == "fail"
    assert by_key["trial_balance"]["status"] == "fail"


async def test_detects_dual_sided_line(db_session):
    accounts = await _accounts(db_session)
    await _raw_entry(
        db_session, None, accounts, entry_date=date(2026, 1, 5),
        legs=[("Cash", 100, 100), ("Rental Income", 0, 100), ("Cash", 0, 100)],
    )
    report = await audit.run_audit(db_session, None)
    by_key = {c["key"]: c for c in report["checks"]}
    assert by_key["line_integrity"]["status"] == "fail"


async def test_detects_single_line_entry(db_session):
    accounts = await _accounts(db_session)
    await _raw_entry(
        db_session, None, accounts, entry_date=date(2026, 1, 5),
        legs=[("Cash", 0, 0)],
    )
    report = await audit.run_audit(db_session, None)
    by_key = {c["key"]: c for c in report["checks"]}
    assert by_key["line_integrity"]["status"] == "fail"


async def test_detects_misfiled_period(db_session):
    accounts = await _accounts(db_session)
    # Create the entry in January's period but with a February date.
    period = await gl_service.get_or_create_period(db_session, None, 2026, 1)
    entry = JournalEntry(
        organization_id=None, period_id=period.id, entry_date=date(2026, 2, 10),
        source="manual", status="posted",
        posted_at=datetime.now(timezone.utc),
    )
    entry.lines = [
        JournalEntryLine(account_id=accounts["Cash"].id, line_number=1,
                         debit=Decimal("5"), credit=Decimal("0")),
        JournalEntryLine(account_id=accounts["Rental Income"].id, line_number=2,
                         debit=Decimal("0"), credit=Decimal("5")),
    ]
    db_session.add(entry)
    await db_session.commit()
    report = await audit.run_audit(db_session, None)
    by_key = {c["key"]: c for c in report["checks"]}
    assert by_key["period_integrity"]["status"] == "fail"


async def test_detects_missing_audit_trail(db_session):
    accounts = await _accounts(db_session)
    await _raw_entry(
        db_session, None, accounts, entry_date=date(2026, 1, 5),
        legs=[("Cash", 5, 0), ("Rental Income", 0, 5)],
        source="", status="draft",
    )
    report = await audit.run_audit(db_session, None)
    by_key = {c["key"]: c for c in report["checks"]}
    assert by_key["audit_trail_integrity"]["status"] == "fail"


async def test_detects_control_account_contamination(db_session):
    accounts = await _accounts(db_session)
    # A rogue-sourced entry moves Accounts Receivable — not an allowed source.
    await _raw_entry(
        db_session, None, accounts, entry_date=date(2026, 1, 5),
        legs=[("Accounts Receivable", 250, 0), ("Rental Income", 0, 250)],
        source="rogue",
    )
    report = await audit.run_audit(db_session, None)
    by_key = {c["key"]: c for c in report["checks"]}
    assert by_key["control_account_integrity"]["status"] == "fail"
    assert any("Accounts Receivable" in f for f in by_key["control_account_integrity"]["findings"])


async def test_detects_cross_organization_account(db_session):
    accounts = await _accounts(db_session)
    other = await _org(db_session)
    other_accounts = await _accounts(db_session, other)
    # Post an entry for org=None but reference a foreign org's Rental Income.
    period = await gl_service.get_or_create_period(db_session, None, 2026, 1)
    entry = JournalEntry(
        organization_id=None, period_id=period.id, entry_date=date(2026, 1, 5),
        source="manual", status="posted",
        posted_at=datetime.now(timezone.utc),
    )
    entry.lines = [
        JournalEntryLine(account_id=accounts["Cash"].id, line_number=1,
                         debit=Decimal("5"), credit=Decimal("0")),
        JournalEntryLine(account_id=other_accounts["Rental Income"].id, line_number=2,
                         debit=Decimal("0"), credit=Decimal("5")),
    ]
    db_session.add(entry)
    await db_session.commit()
    report = await audit.run_audit(db_session, None)
    by_key = {c["key"]: c for c in report["checks"]}
    assert by_key["account_scope_integrity"]["status"] == "fail"


# ─── API surface ───────────────────────────────────────────────────────────────

async def test_audit_report_endpoint_attests(client, accountant_user, healthy_ledger):
    resp = await client.get(
        "/api/v1/financials/audit-report", headers=auth_headers(accountant_user)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["attested"] is True
    assert body["checks_failed"] == 0
    assert Decimal(body["total_debits"]) == Decimal(body["total_credits"])


async def test_audit_report_endpoint_flags_corruption(db_session, client, accountant_user):
    accounts = await _accounts(db_session)
    await _raw_entry(
        db_session, None, accounts, entry_date=date(2026, 1, 5),
        legs=[("Cash", 100, 0), ("Rental Income", 0, 90)],
    )
    resp = await client.get(
        "/api/v1/financials/audit-report", headers=auth_headers(accountant_user)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["attested"] is False
    assert body["checks_failed"] >= 1


async def test_audit_report_forbidden_for_viewer(client, viewer_user):
    resp = await client.get(
        "/api/v1/financials/audit-report", headers=auth_headers(viewer_user)
    )
    assert resp.status_code == 403


async def test_empty_ledger_attests(db_session):
    # A brand-new org with no postings is trivially valid.
    await _accounts(db_session)
    report = await audit.run_audit(db_session, None)
    assert report["attested"] is True
    assert report["entry_count"] == 0
    assert report["total_debits"] == Decimal("0.00")
