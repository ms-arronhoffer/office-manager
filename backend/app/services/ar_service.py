"""Accounts-receivable-lite service layer (Phase 1.1).

Keeps the ``/api/v1/ar`` router thin by holding the invoice/receipt rules and the
general-ledger postings:

  - invoice totalling and derived open/partial/paid status from recorded receipts
  - finalizing a draft invoice and posting ``Dr Accounts Receivable / Cr revenue``
  - recording a receipt and posting ``Dr Cash / Cr Accounts Receivable``
  - idempotent re-posting via the ``ar`` GL source tag
  - an AR aging report over open (unpaid) finalized invoices
  - building a draft invoice from a finalized CAM true-up

All amounts are USD; multi-currency / FX is deferred. Postings reuse the shared
``gl_service`` helpers so AR entries land in the same audit-grade ledger as lease,
CAM, and AP entries. This mirrors the accounts-payable module (``ap_service``) on
the sell side.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.customer_invoice import CustomerInvoice, CustomerReceipt

TWO = Decimal("0.01")

# GL source tag for everything posted by this module.
AR_SOURCE = "ar"

# AR-specific accounts ensured present before posting. Cash (1000) is already in
# the default chart of accounts; Accounts Receivable and a generic Service
# Revenue account are ensured here so postings never fail on a missing account.
AR_ACCOUNTS: list[tuple[str, str, str]] = [
    ("1100", "Accounts Receivable", "asset"),
    ("4200", "Service Revenue", "revenue"),
]

# Default revenue account used when a CAM true-up is turned into an invoice.
CAM_REVENUE_ACCOUNT_NAME = "CAM Recovery Income"

# Standard aging buckets (days past due). ``current`` covers not-yet-due and
# 0-30 days; the remaining buckets are 31-60, 61-90, and 90+.
AGING_BUCKETS = ("current", "1_30", "31_60", "61_90", "90_plus")


class ARError(ValueError):
    """Raised for accounts-receivable rule violations."""


def _q(value) -> Decimal:
    """Round to 2 decimal places (currency)."""
    return Decimal(str(value or 0)).quantize(TWO, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Totals and derived status
# ---------------------------------------------------------------------------

def invoice_total(invoice: CustomerInvoice) -> Decimal:
    """Sum of the invoice's line amounts."""
    return _q(sum((_q(line.amount) for line in invoice.lines), Decimal("0")))


def amount_received(invoice: CustomerInvoice) -> Decimal:
    """Sum of receipts recorded against the invoice."""
    return _q(sum((_q(r.amount) for r in invoice.receipts), Decimal("0")))


def balance_due(invoice: CustomerInvoice) -> Decimal:
    """Outstanding balance: total less receipts (never negative)."""
    bal = _q(invoice_total(invoice) - amount_received(invoice))
    return bal if bal > 0 else Decimal("0.00")


def receipt_state(invoice: CustomerInvoice) -> str:
    """Derive open / partial / paid from the invoice total and its receipts."""
    total = invoice_total(invoice)
    received = amount_received(invoice)
    if received <= 0:
        return "open"
    if received >= total:
        return "paid"
    return "partial"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_currency(currency: str | None) -> str:
    """Only USD is supported; FX is deferred."""
    cur = (currency or "USD").upper()
    if cur != "USD":
        raise ARError("Only USD invoices are supported; multi-currency is not yet available.")
    return cur


def validate_lines(lines: list[dict]) -> None:
    """Ensure an invoice has at least one line and every line is a positive amount."""
    if not lines:
        raise ARError("An invoice must have at least one line.")
    for line in lines:
        if line.get("account_id") is None:
            raise ARError("Each invoice line requires an account_id.")
        if _q(line.get("amount")) <= 0:
            raise ARError("Each invoice line amount must be greater than zero.")


# ---------------------------------------------------------------------------
# GL posting — invoice
# ---------------------------------------------------------------------------

async def post_invoice_to_gl(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    invoice: CustomerInvoice,
    *,
    posted_by_id: uuid.UUID | None = None,
):
    """Post a finalized invoice: ``Dr Accounts Receivable / Cr each revenue line``.

    Re-posting first removes any prior ``ar``-sourced entry for the invoice so the
    ledger is not double-counted.
    """
    from app.services import gl_service

    if invoice.status != "finalized":
        raise ARError("Only a finalized invoice can be posted to the GL.")

    await gl_service.seed_default_accounts(db, organization_id)
    await gl_service.ensure_accounts(db, organization_id, AR_ACCOUNTS)
    account_map = await gl_service.get_account_map(db, organization_id)
    ar_account = account_map["Accounts Receivable"]

    # Idempotent re-post: drop any prior ar-sourced entry for this invoice.
    await gl_service.delete_entries_by_source(
        db, organization_id, source=AR_SOURCE, source_ref=_invoice_ref(invoice), commit=False
    )
    invoice.journal_entry_id = None

    total = invoice_total(invoice)
    if total <= 0:
        await db.commit()
        return None

    # Debit Accounts Receivable for the invoice total.
    lines: list[dict] = [
        {"account_id": ar_account.id, "debit": total, "credit": 0}
    ]
    # Credit each revenue allocation line.
    for line in invoice.lines:
        amount = _q(line.amount)
        if amount <= 0:
            continue
        lines.append(
            {
                "account_id": line.account_id,
                "debit": 0,
                "credit": amount,
                "memo": line.description,
            }
        )

    entry = await gl_service.create_journal_entry(
        db,
        organization_id,
        entry_date=invoice.invoice_date,
        lines=lines,
        memo=_invoice_memo(invoice),
        source=AR_SOURCE,
        source_ref=_invoice_ref(invoice),
        posted_by_id=posted_by_id,
        commit=False,
    )
    invoice.journal_entry_id = entry.id
    await db.commit()
    await db.refresh(entry)
    return entry


# ---------------------------------------------------------------------------
# GL posting — receipt
# ---------------------------------------------------------------------------

async def post_receipt_to_gl(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    receipt: CustomerReceipt,
    *,
    posted_by_id: uuid.UUID | None = None,
):
    """Post a receipt: ``Dr Cash / Cr Accounts Receivable``.

    Idempotent: re-posting removes any prior ``ar``-sourced entry for the receipt.
    """
    from app.services import gl_service

    await gl_service.seed_default_accounts(db, organization_id)
    await gl_service.ensure_accounts(db, organization_id, AR_ACCOUNTS)
    account_map = await gl_service.get_account_map(db, organization_id)
    ar_account = account_map["Accounts Receivable"]
    cash = account_map["Cash"]

    await gl_service.delete_entries_by_source(
        db, organization_id, source=AR_SOURCE, source_ref=_receipt_ref(receipt),
        commit=False,
    )
    receipt.journal_entry_id = None

    amount = _q(receipt.amount)
    if amount <= 0:
        await db.commit()
        return None

    lines = [
        {"account_id": cash.id, "debit": amount, "credit": 0},
        {"account_id": ar_account.id, "debit": 0, "credit": amount},
    ]
    entry = await gl_service.create_journal_entry(
        db,
        organization_id,
        entry_date=receipt.receipt_date,
        lines=lines,
        memo=_receipt_memo(receipt),
        source=AR_SOURCE,
        source_ref=_receipt_ref(receipt),
        posted_by_id=posted_by_id,
        commit=False,
    )
    receipt.journal_entry_id = entry.id
    await db.commit()
    await db.refresh(entry)
    return entry


async def remove_receipt_entry(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    receipt: CustomerReceipt,
    *,
    commit: bool = True,
) -> int:
    """Delete the GL entry posted for a receipt (used when a receipt is removed)."""
    from app.services import gl_service

    return await gl_service.delete_entries_by_source(
        db, organization_id, source=AR_SOURCE, source_ref=_receipt_ref(receipt),
        commit=commit,
    )


async def remove_invoice_entry(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    invoice: CustomerInvoice,
    *,
    commit: bool = True,
) -> int:
    """Delete the GL entry posted for an invoice (used when an invoice is voided)."""
    from app.services import gl_service

    return await gl_service.delete_entries_by_source(
        db, organization_id, source=AR_SOURCE, source_ref=_invoice_ref(invoice),
        commit=commit,
    )


# ---------------------------------------------------------------------------
# Aging report
# ---------------------------------------------------------------------------

def _bucket_for(days_past_due: int) -> str:
    """Map a days-past-due count to an aging bucket key."""
    if days_past_due <= 0:
        return "current"
    if days_past_due <= 30:
        return "1_30"
    if days_past_due <= 60:
        return "31_60"
    if days_past_due <= 90:
        return "61_90"
    return "90_plus"


async def aging_report(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    *,
    as_of: date | None = None,
) -> dict:
    """Build an AR aging report over open (unpaid) finalized invoices.

    Each open invoice's outstanding balance is bucketed by how far past its due
    date (or invoice date when no due date) it is, as of ``as_of`` (today by
    default). Returns per-customer rows plus grand totals per bucket.
    """
    as_of = as_of or date.today()

    invoices = (
        await db.execute(
            select(CustomerInvoice)
            .where(
                CustomerInvoice.organization_id == organization_id,
                CustomerInvoice.status == "finalized",
            )
            .options(
                selectinload(CustomerInvoice.lines),
                selectinload(CustomerInvoice.receipts),
                selectinload(CustomerInvoice.customer),
            )
        )
    ).scalars().unique().all()

    def _empty_buckets() -> dict[str, Decimal]:
        return {b: Decimal("0.00") for b in AGING_BUCKETS}

    by_customer: dict[uuid.UUID, dict] = {}
    totals = _empty_buckets()
    grand_total = Decimal("0.00")

    for invoice in invoices:
        outstanding = balance_due(invoice)
        if outstanding <= 0:
            continue
        due = invoice.due_date or invoice.invoice_date
        bucket = _bucket_for((as_of - due).days)

        row = by_customer.setdefault(
            invoice.customer_id,
            {
                "customer_id": invoice.customer_id,
                "customer_name": invoice.customer.name if invoice.customer else None,
                "buckets": _empty_buckets(),
                "total": Decimal("0.00"),
                "invoices": [],
            },
        )
        row["buckets"][bucket] = _q(row["buckets"][bucket] + outstanding)
        row["total"] = _q(row["total"] + outstanding)
        row["invoices"].append(
            {
                "invoice_id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "invoice_date": invoice.invoice_date,
                "due_date": invoice.due_date,
                "balance_due": outstanding,
                "bucket": bucket,
            }
        )
        totals[bucket] = _q(totals[bucket] + outstanding)
        grand_total = _q(grand_total + outstanding)

    customers = sorted(
        by_customer.values(), key=lambda r: (r["customer_name"] or "").lower()
    )
    return {
        "as_of": as_of,
        "buckets": list(AGING_BUCKETS),
        "customers": customers,
        "totals": totals,
        "grand_total": grand_total,
    }


# ---------------------------------------------------------------------------
# CAM true-up -> invoice
# ---------------------------------------------------------------------------

def build_invoice_lines_from_cam(recon, account_map: dict) -> tuple[list[dict], str]:
    """Return draft invoice line inputs and a memo for a finalized CAM true-up.

    A positive CAM ``balance_due`` (tenant owes) becomes a single revenue line
    credited to CAM Recovery Income. A zero or negative balance (nothing owed or
    a credit due to the tenant) is not billable and raises ``ARError``.
    """
    balance = _q(getattr(recon, "balance_due", 0))
    if balance <= 0:
        raise ARError(
            "CAM reconciliation has no tenant true-up balance to invoice."
        )
    account = account_map.get(CAM_REVENUE_ACCOUNT_NAME)
    if account is None:
        raise ARError(
            f"Revenue account '{CAM_REVENUE_ACCOUNT_NAME}' is not configured."
        )
    memo = f"CAM true-up {recon.year} (reconciliation {recon.id})"
    lines = [
        {
            "account_id": account.id,
            "amount": balance,
            "description": memo,
        }
    ]
    return lines, memo


# ---------------------------------------------------------------------------
# Source-ref / memo helpers
# ---------------------------------------------------------------------------

def _invoice_ref(invoice: CustomerInvoice) -> str:
    return f"invoice:{invoice.id}"


def _receipt_ref(receipt: CustomerReceipt) -> str:
    return f"receipt:{receipt.id}"


def _invoice_memo(invoice: CustomerInvoice) -> str:
    label = invoice.invoice_number or str(invoice.id)
    return f"Customer invoice {label}"


def _receipt_memo(receipt: CustomerReceipt) -> str:
    return f"Receipt on customer invoice {receipt.invoice_id}"


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------

async def get_invoice(
    db: AsyncSession, invoice_id: uuid.UUID, organization_id: uuid.UUID | None
) -> CustomerInvoice | None:
    """Load an invoice with its lines and receipts eagerly for the given org."""
    return (
        await db.execute(
            select(CustomerInvoice)
            .where(
                CustomerInvoice.id == invoice_id,
                CustomerInvoice.organization_id == organization_id,
            )
            .options(
                selectinload(CustomerInvoice.lines),
                selectinload(CustomerInvoice.receipts),
            )
        )
    ).scalar_one_or_none()
