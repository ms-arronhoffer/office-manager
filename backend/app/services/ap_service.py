"""Accounts-payable-lite service layer (Phase 5).

Keeps the ``/api/v1/ap`` router thin by holding the bill/payment rules and the
general-ledger postings:

  - bill totalling and derived open/partial/paid status from recorded payments
  - finalizing a draft bill and posting ``Dr expense / Cr Accounts Payable``
  - recording a payment and posting ``Dr Accounts Payable / Cr Cash``
  - idempotent re-posting via the ``ap`` GL source tag

All amounts are USD; multi-currency / FX is deferred. Postings reuse the shared
``gl_service`` helpers so AP entries land in the same audit-grade ledger as lease,
CAM, and lifecycle entries.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vendor_bill import VendorBill, VendorPayment

TWO = Decimal("0.01")

# GL source tag for everything posted by this module.
AP_SOURCE = "ap"

# AP-specific accounts ensured present before posting. Cash (1000) is already in
# the default chart of accounts; Accounts Payable is added here.
AP_ACCOUNTS: list[tuple[str, str, str]] = [
    ("2200", "Accounts Payable", "liability"),
]


class APError(ValueError):
    """Raised for accounts-payable rule violations."""


def _q(value) -> Decimal:
    """Round to 2 decimal places (currency)."""
    return Decimal(str(value or 0)).quantize(TWO, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Totals and derived status
# ---------------------------------------------------------------------------

def bill_total(bill: VendorBill) -> Decimal:
    """Sum of the bill's line amounts."""
    return _q(sum((_q(line.amount) for line in bill.lines), Decimal("0")))


def amount_paid(bill: VendorBill) -> Decimal:
    """Sum of payments recorded against the bill."""
    return _q(sum((_q(p.amount) for p in bill.payments), Decimal("0")))


def balance_due(bill: VendorBill) -> Decimal:
    """Outstanding balance: total less payments (never negative)."""
    bal = _q(bill_total(bill) - amount_paid(bill))
    return bal if bal > 0 else Decimal("0.00")


def payment_state(bill: VendorBill) -> str:
    """Derive open / partial / paid from the bill total and its payments."""
    total = bill_total(bill)
    paid = amount_paid(bill)
    if paid <= 0:
        return "open"
    if paid >= total:
        return "paid"
    return "partial"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_currency(currency: str | None) -> str:
    """Only USD is supported; FX is deferred."""
    cur = (currency or "USD").upper()
    if cur != "USD":
        raise APError("Only USD bills are supported; multi-currency is not yet available.")
    return cur


def validate_lines(lines: list[dict]) -> None:
    """Ensure a bill has at least one line and every line is a positive amount."""
    if not lines:
        raise APError("A bill must have at least one line.")
    for line in lines:
        if line.get("account_id") is None:
            raise APError("Each bill line requires an account_id.")
        if _q(line.get("amount")) <= 0:
            raise APError("Each bill line amount must be greater than zero.")


# ---------------------------------------------------------------------------
# GL posting — bill
# ---------------------------------------------------------------------------

async def post_bill_to_gl(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    bill: VendorBill,
    *,
    posted_by_id: uuid.UUID | None = None,
):
    """Post a finalized bill: ``Dr each expense line / Cr Accounts Payable``.

    Re-posting first removes any prior ``ap``-sourced entry for the bill so the
    ledger is not double-counted.
    """
    from app.services import gl_service

    if bill.status != "finalized":
        raise APError("Only a finalized bill can be posted to the GL.")

    await gl_service.seed_default_accounts(db, organization_id)
    await gl_service.ensure_accounts(db, organization_id, AP_ACCOUNTS)
    account_map = await gl_service.get_account_map(db, organization_id)
    ap_account = account_map["Accounts Payable"]

    # Idempotent re-post: drop any prior ap-sourced entry for this bill.
    await gl_service.delete_entries_by_source(
        db, organization_id, source=AP_SOURCE, source_ref=_bill_ref(bill), commit=False
    )
    bill.journal_entry_id = None

    total = bill_total(bill)
    if total <= 0:
        await db.commit()
        return None

    # Debit each expense allocation line.
    lines: list[dict] = []
    for line in bill.lines:
        amount = _q(line.amount)
        if amount <= 0:
            continue
        lines.append(
            {
                "account_id": line.account_id,
                "debit": amount,
                "credit": 0,
                "memo": line.description,
            }
        )
    # Credit Accounts Payable for the bill total.
    lines.append({"account_id": ap_account.id, "debit": 0, "credit": total})

    entry = await gl_service.create_journal_entry(
        db,
        organization_id,
        entry_date=bill.bill_date,
        lines=lines,
        memo=_bill_memo(bill),
        source=AP_SOURCE,
        source_ref=_bill_ref(bill),
        posted_by_id=posted_by_id,
        commit=False,
    )
    bill.journal_entry_id = entry.id
    await db.commit()
    await db.refresh(entry)
    return entry


# ---------------------------------------------------------------------------
# GL posting — payment
# ---------------------------------------------------------------------------

async def post_payment_to_gl(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    payment: VendorPayment,
    *,
    posted_by_id: uuid.UUID | None = None,
):
    """Post a payment: ``Dr Accounts Payable / Cr Cash``.

    Idempotent: re-posting removes any prior ``ap``-sourced entry for the payment.
    """
    from app.services import gl_service

    await gl_service.seed_default_accounts(db, organization_id)
    await gl_service.ensure_accounts(db, organization_id, AP_ACCOUNTS)
    account_map = await gl_service.get_account_map(db, organization_id)
    ap_account = account_map["Accounts Payable"]
    cash = account_map["Cash"]

    await gl_service.delete_entries_by_source(
        db, organization_id, source=AP_SOURCE, source_ref=_payment_ref(payment),
        commit=False,
    )
    payment.journal_entry_id = None

    amount = _q(payment.amount)
    if amount <= 0:
        await db.commit()
        return None

    lines = [
        {"account_id": ap_account.id, "debit": amount, "credit": 0},
        {"account_id": cash.id, "debit": 0, "credit": amount},
    ]
    entry = await gl_service.create_journal_entry(
        db,
        organization_id,
        entry_date=payment.payment_date,
        lines=lines,
        memo=_payment_memo(payment),
        source=AP_SOURCE,
        source_ref=_payment_ref(payment),
        posted_by_id=posted_by_id,
        commit=False,
    )
    payment.journal_entry_id = entry.id
    await db.commit()
    await db.refresh(entry)
    return entry


async def remove_payment_entry(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    payment: VendorPayment,
    *,
    commit: bool = True,
) -> int:
    """Delete the GL entry posted for a payment (used when a payment is removed)."""
    from app.services import gl_service

    return await gl_service.delete_entries_by_source(
        db, organization_id, source=AP_SOURCE, source_ref=_payment_ref(payment),
        commit=commit,
    )


# ---------------------------------------------------------------------------
# Source-ref / memo helpers
# ---------------------------------------------------------------------------

def _bill_ref(bill: VendorBill) -> str:
    return f"bill:{bill.id}"


def _payment_ref(payment: VendorPayment) -> str:
    return f"payment:{payment.id}"


def _bill_memo(bill: VendorBill) -> str:
    label = bill.bill_number or str(bill.id)
    return f"Vendor bill {label}"


def _payment_memo(payment: VendorPayment) -> str:
    return f"Payment on vendor bill {payment.bill_id}"


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------

async def get_bill(
    db: AsyncSession, bill_id: uuid.UUID, organization_id: uuid.UUID | None
) -> VendorBill | None:
    """Load a bill with its lines and payments eagerly for the given org."""
    from sqlalchemy.orm import selectinload

    return (
        await db.execute(
            select(VendorBill)
            .where(
                VendorBill.id == bill_id,
                VendorBill.organization_id == organization_id,
            )
            .options(
                selectinload(VendorBill.lines),
                selectinload(VendorBill.payments),
            )
        )
    ).scalar_one_or_none()
