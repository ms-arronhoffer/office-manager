"""Rent collection & payments-in service layer (Phase 2.3).

Holds the inbound-money rules so the ``/api/v1/rent`` router stays thin:

  - recurring rent invoice generation off :class:`~app.models.rent.RentCharge`
    schedules, reusing the Phase 1.1 accounts-receivable ledger (invoices are
    ``CustomerInvoice`` rows tagged ``source="rent"``) so they post
    ``Dr Accounts Receivable / Cr Rental Income`` through the shared GL
  - late-fee automation over overdue rent invoices
  - inbound payments (ACH/card) via the pluggable payment processor, recording a
    ``CustomerReceipt`` that posts ``Dr Cash / Cr Accounts Receivable``
  - security-deposit tracking with its own liability postings
    (``Dr Cash / Cr Security Deposits Held`` on receipt; the reverse on return,
    forfeited amounts recognised as income)

All amounts are USD. GL postings reuse :mod:`app.services.ar_service` and
:mod:`app.services.gl_service` so rent lands in the same audit-grade ledger as
lease, CAM, AR, and AP entries.
"""

from __future__ import annotations

import calendar
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.customer_invoice import Customer, CustomerInvoice, CustomerInvoiceLine
from app.models.general_ledger import GLAccount
from app.models.rent import RentCharge, SecurityDeposit
from app.models.resident import Resident, ResidentLease, ResidentLeaseOccupant
from app.services import ar_service, gl_service
from app.utils import payment_processor

TWO = Decimal("0.01")

# Provenance tags carried on generated AR invoices.
RENT_INVOICE_SOURCE = "rent"
LATE_FEE_INVOICE_SOURCE = "rent_late_fee"
# GL source tag for security-deposit journal entries (they bypass AR).
DEPOSIT_GL_SOURCE = "deposit"

# Feature-specific accounts ensured present before posting rent/deposit entries.
RENT_ACCOUNTS: list[tuple[str, str, str]] = [
    ("4000", "Rental Income", "revenue"),
    ("4300", "Late Fee Income", "revenue"),
    ("4400", "Forfeited Deposit Income", "revenue"),
    ("2300", "Security Deposits Held", "liability"),
]


class RentError(ValueError):
    """Raised for rent-collection rule violations."""


def _q(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(TWO, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Account / customer helpers
# ---------------------------------------------------------------------------

async def ensure_rent_accounts(db: AsyncSession, organization_id: uuid.UUID | None) -> None:
    """Make sure the rent/deposit GL accounts exist for the org."""
    await gl_service.seed_default_accounts(db, organization_id)
    await gl_service.ensure_accounts(db, organization_id, RENT_ACCOUNTS, commit=False)


async def _account_by_code(
    db: AsyncSession, organization_id: uuid.UUID | None, code: str
) -> GLAccount:
    acct = (
        await db.execute(
            select(GLAccount).where(
                GLAccount.organization_id == organization_id,
                GLAccount.code == code,
            )
        )
    ).scalar_one_or_none()
    if acct is None:
        raise RentError(f"GL account with code {code} is not configured.")
    return acct


async def _load_lease(
    db: AsyncSession, organization_id: uuid.UUID | None, lease_id: uuid.UUID
) -> ResidentLease:
    lease = (
        await db.execute(
            select(ResidentLease)
            .where(
                ResidentLease.id == lease_id,
                ResidentLease.organization_id == organization_id,
            )
            .options(
                selectinload(ResidentLease.occupants).selectinload(
                    ResidentLeaseOccupant.resident
                ),
                selectinload(ResidentLease.unit),
            )
        )
    ).scalar_one_or_none()
    if lease is None:
        raise RentError("Resident lease not found.")
    return lease


def primary_resident(lease: ResidentLease) -> Resident | None:
    """Return the primary occupant (or the first occupant) of a lease."""
    occupants = list(lease.occupants or [])
    if not occupants:
        return None
    primary = next((o for o in occupants if o.is_primary), None)
    chosen = primary or occupants[0]
    return chosen.resident


async def get_or_create_customer_for_resident(
    db: AsyncSession, organization_id: uuid.UUID | None, resident: Resident
) -> Customer:
    """Return the AR customer used to bill a resident, creating it on first use."""
    if resident.customer_id:
        existing = (
            await db.execute(
                select(Customer).where(
                    Customer.id == resident.customer_id,
                    Customer.organization_id == organization_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    customer = Customer(
        organization_id=organization_id,
        name=f"{resident.first_name} {resident.last_name}".strip() or "Resident",
        contact_name=f"{resident.first_name} {resident.last_name}".strip() or None,
        contact_email=resident.email,
        contact_phone=resident.phone,
    )
    db.add(customer)
    await db.flush()
    resident.customer_id = customer.id
    return customer


# ---------------------------------------------------------------------------
# Recurring rent invoice generation
# ---------------------------------------------------------------------------

def _due_date(period_start: date, day_of_month: int) -> date:
    """The due date within ``period_start``'s month, clamped to a valid day."""
    last_day = calendar.monthrange(period_start.year, period_start.month)[1]
    day = min(max(int(day_of_month or 1), 1), last_day)
    return date(period_start.year, period_start.month, day)


def _add_month(d: date) -> date:
    """First day of the month after ``d``'s month."""
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def _periods_due(charge: RentCharge, as_of: date) -> list[date]:
    """First-of-month period starts owed by ``charge`` through ``as_of``.

    Bills every month from the charge's start (or its last billed period) up to
    and including the month of ``as_of``, but never a period whose due date is in
    the future, and never past the charge's end date.
    """
    if not charge.active:
        return []
    start = charge.start_date or as_of
    # First unbilled period start (first of month).
    if charge.last_billed_period is not None:
        cursor = _add_month(charge.last_billed_period.replace(day=1))
    else:
        cursor = start.replace(day=1)

    periods: list[date] = []
    limit_month = as_of.replace(day=1)
    while cursor <= limit_month:
        if charge.end_date is not None and cursor > charge.end_date:
            break
        # Only bill once the period's due date has actually arrived.
        if _due_date(cursor, charge.day_of_month) <= as_of:
            periods.append(cursor)
        cursor = _add_month(cursor)
    return periods


def _rent_source_ref(charge: RentCharge, period_start: date) -> str:
    return f"rentcharge:{charge.id}:{period_start.isoformat()}"


async def _invoice_exists(
    db: AsyncSession, organization_id: uuid.UUID | None, source: str, source_ref: str
) -> bool:
    found = (
        await db.execute(
            select(CustomerInvoice.id).where(
                CustomerInvoice.organization_id == organization_id,
                CustomerInvoice.source == source,
                CustomerInvoice.source_ref == source_ref,
            )
        )
    ).first()
    return found is not None


async def generate_rent_invoice(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    charge: RentCharge,
    period_start: date,
    *,
    posted_by_id: uuid.UUID | None = None,
) -> CustomerInvoice | None:
    """Create, finalize, and post one rent invoice for a charge's period.

    Idempotent: returns ``None`` if an invoice for this charge+period already
    exists.
    """
    source_ref = _rent_source_ref(charge, period_start)
    if await _invoice_exists(db, organization_id, RENT_INVOICE_SOURCE, source_ref):
        return None

    lease = await _load_lease(db, organization_id, charge.resident_lease_id)
    resident = primary_resident(lease)
    if resident is None:
        raise RentError("Cannot bill a lease with no occupants.")

    await ensure_rent_accounts(db, organization_id)
    customer = await get_or_create_customer_for_resident(db, organization_id, resident)
    revenue = await _account_by_code(db, organization_id, charge.revenue_account_code)

    amount = _q(charge.amount)
    due = _due_date(period_start, charge.day_of_month)
    description = charge.description or f"{charge.charge_type.title()} — {period_start:%B %Y}"

    invoice = CustomerInvoice(
        organization_id=organization_id,
        customer_id=customer.id,
        invoice_date=due,
        due_date=due,
        currency="USD",
        memo=description,
        total_amount=amount,
        source=RENT_INVOICE_SOURCE,
        source_ref=source_ref,
        status="finalized",
        finalized_at=datetime.now(timezone.utc),
        finalized_by_id=posted_by_id,
        lines=[
            CustomerInvoiceLine(
                account_id=revenue.id,
                line_number=1,
                description=description,
                amount=amount,
            )
        ],
    )
    db.add(invoice)
    await db.flush()

    await ar_service.post_invoice_to_gl(
        db, organization_id, invoice, posted_by_id=posted_by_id
    )
    charge.last_billed_period = period_start
    await db.commit()
    await db.refresh(invoice)
    return invoice


async def run_recurring_billing(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    *,
    as_of: date | None = None,
    posted_by_id: uuid.UUID | None = None,
) -> dict:
    """Generate all due rent invoices across active charges, up to ``as_of``."""
    as_of = as_of or date.today()
    charges = (
        await db.execute(
            select(RentCharge).where(
                RentCharge.organization_id == organization_id,
                RentCharge.active.is_(True),
                RentCharge.is_deleted.is_(False),
            )
        )
    ).scalars().all()

    generated: list[uuid.UUID] = []
    for charge in charges:
        for period_start in _periods_due(charge, as_of):
            invoice = await generate_rent_invoice(
                db, organization_id, charge, period_start, posted_by_id=posted_by_id
            )
            if invoice is not None:
                generated.append(invoice.id)
    return {"generated": len(generated), "invoice_ids": [str(i) for i in generated]}


# ---------------------------------------------------------------------------
# Late-fee automation
# ---------------------------------------------------------------------------

def _late_fee_amount(charge: RentCharge, balance: Decimal) -> Decimal:
    """Compute the late fee for an overdue balance per the charge policy."""
    if charge.late_fee_type == "flat":
        return _q(charge.late_fee_amount)
    if charge.late_fee_type == "percent":
        pct = Decimal(str(charge.late_fee_amount or 0)) / Decimal("100")
        return _q(balance * pct)
    return Decimal("0.00")


async def apply_late_fees(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    *,
    as_of: date | None = None,
    posted_by_id: uuid.UUID | None = None,
) -> dict:
    """Assess late fees on overdue, still-open rent invoices.

    For each active charge with a late-fee policy, any of its rent invoices that
    is past ``due_date + grace_days`` and still carries a balance gets a separate
    late-fee invoice (idempotent per originating invoice).
    """
    as_of = as_of or date.today()
    charges = (
        await db.execute(
            select(RentCharge).where(
                RentCharge.organization_id == organization_id,
                RentCharge.active.is_(True),
                RentCharge.is_deleted.is_(False),
                RentCharge.late_fee_type != "none",
            )
        )
    ).scalars().all()
    charge_by_lease: dict[uuid.UUID, RentCharge] = {}
    for c in charges:
        # Prefer the primary rent charge when several exist for one lease.
        if c.resident_lease_id not in charge_by_lease or c.charge_type == "rent":
            charge_by_lease[c.resident_lease_id] = c
    if not charge_by_lease:
        return {"assessed": 0, "invoice_ids": []}

    await ensure_rent_accounts(db, organization_id)
    late_account = await _account_by_code(db, organization_id, "4300")

    rent_invoices = (
        await db.execute(
            select(CustomerInvoice)
            .where(
                CustomerInvoice.organization_id == organization_id,
                CustomerInvoice.source == RENT_INVOICE_SOURCE,
                CustomerInvoice.status == "finalized",
            )
            .options(
                selectinload(CustomerInvoice.lines),
                selectinload(CustomerInvoice.receipts),
            )
        )
    ).scalars().unique().all()

    assessed: list[uuid.UUID] = []
    for inv in rent_invoices:
        if ar_service.balance_due(inv) <= 0:
            continue
        # Recover the originating charge/period from the invoice source_ref.
        try:
            _, charge_id_str, _period = (inv.source_ref or "").split(":", 2)
            charge_id = uuid.UUID(charge_id_str)
        except (ValueError, AttributeError):
            continue
        charge = next(
            (c for c in charges if c.id == charge_id), None
        ) or charge_by_lease.get(charge_id)
        if charge is None or charge.late_fee_type == "none":
            continue
        due = inv.due_date or inv.invoice_date
        days_past = (as_of - due).days
        if days_past <= charge.grace_days:
            continue

        late_ref = f"latefee:{inv.id}"
        if await _invoice_exists(db, organization_id, LATE_FEE_INVOICE_SOURCE, late_ref):
            continue
        fee = _late_fee_amount(charge, ar_service.balance_due(inv))
        if fee <= 0:
            continue

        late_inv = CustomerInvoice(
            organization_id=organization_id,
            customer_id=inv.customer_id,
            invoice_date=as_of,
            due_date=as_of,
            currency="USD",
            memo=f"Late fee — invoice {inv.invoice_number or inv.id}",
            total_amount=fee,
            source=LATE_FEE_INVOICE_SOURCE,
            source_ref=late_ref,
            status="finalized",
            finalized_at=datetime.now(timezone.utc),
            finalized_by_id=posted_by_id,
            lines=[
                CustomerInvoiceLine(
                    account_id=late_account.id,
                    line_number=1,
                    description="Late fee",
                    amount=fee,
                )
            ],
        )
        db.add(late_inv)
        await db.flush()
        await ar_service.post_invoice_to_gl(
            db, organization_id, late_inv, posted_by_id=posted_by_id
        )
        assessed.append(late_inv.id)

    await db.commit()
    return {"assessed": len(assessed), "invoice_ids": [str(i) for i in assessed]}


# ---------------------------------------------------------------------------
# Inbound payments
# ---------------------------------------------------------------------------

async def record_rent_payment(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    invoice: CustomerInvoice,
    amount: Decimal,
    *,
    method: str = "ach",
    payment_token: str | None = None,
    receipt_date: date | None = None,
    reference: str | None = None,
    created_by_id: uuid.UUID | None = None,
) -> dict:
    """Charge a resident (via the processor) and record the receipt in the GL.

    When ``method`` is ``card``/``ach`` and a ``payment_token`` is supplied, the
    payment processor is asked to capture the funds. Regardless of whether a live
    processor captured them, a :class:`CustomerReceipt` is recorded and posted so
    offline/manual payments (check, cash, or an unconfigured processor) still land
    in the ledger. The processor outcome is returned for the caller to surface.
    """
    from app.models.customer_invoice import CustomerReceipt

    amount = _q(amount)
    if amount <= 0:
        raise RentError("Payment amount must be greater than zero.")
    if invoice.status != "finalized":
        raise RentError("Payments can only be recorded against a finalized invoice.")

    charge_result = None
    processor_ref = reference
    if method in payment_processor.PAYMENT_METHODS and payment_token:
        charge_result = await payment_processor.charge_payment(
            amount,
            method=method,
            payment_token=payment_token,
            description=f"Rent payment for invoice {invoice.invoice_number or invoice.id}",
        )
        if charge_result.captured and charge_result.processor_ref:
            processor_ref = charge_result.processor_ref

    receipt = CustomerReceipt(
        organization_id=organization_id,
        invoice_id=invoice.id,
        receipt_date=receipt_date or date.today(),
        amount=amount,
        method=method,
        reference=processor_ref,
        created_by_id=created_by_id,
    )
    db.add(receipt)
    await db.flush()
    await ar_service.post_receipt_to_gl(
        db, organization_id, receipt, posted_by_id=created_by_id
    )
    await db.commit()
    await db.refresh(receipt)
    return {
        "receipt": receipt,
        "captured": bool(charge_result and charge_result.captured),
        "processor_status": charge_result.status if charge_result else "offline",
    }


# ---------------------------------------------------------------------------
# Security deposits
# ---------------------------------------------------------------------------

def _deposit_ref(deposit: SecurityDeposit) -> str:
    return f"deposit:{deposit.id}"


def _deposit_return_ref(deposit: SecurityDeposit) -> str:
    return f"deposit_return:{deposit.id}"


async def record_deposit(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    *,
    resident_lease_id: uuid.UUID,
    amount: Decimal,
    held_date: date | None = None,
    notes: str | None = None,
    posted_by_id: uuid.UUID | None = None,
) -> SecurityDeposit:
    """Record a received deposit: ``Dr Cash / Cr Security Deposits Held``."""
    amount = _q(amount)
    if amount <= 0:
        raise RentError("Deposit amount must be greater than zero.")
    lease = await _load_lease(db, organization_id, resident_lease_id)

    await ensure_rent_accounts(db, organization_id)
    account_map = await gl_service.get_account_map(db, organization_id)
    cash = account_map["Cash"]
    held = account_map["Security Deposits Held"]

    deposit = SecurityDeposit(
        organization_id=organization_id,
        resident_lease_id=lease.id,
        amount=amount,
        held_date=held_date or date.today(),
        status="held",
        notes=notes,
    )
    db.add(deposit)
    await db.flush()

    entry = await gl_service.create_journal_entry(
        db,
        organization_id,
        entry_date=deposit.held_date,
        lines=[
            {"account_id": cash.id, "debit": amount, "credit": 0},
            {"account_id": held.id, "debit": 0, "credit": amount},
        ],
        memo=f"Security deposit received (lease {lease.id})",
        source=DEPOSIT_GL_SOURCE,
        source_ref=_deposit_ref(deposit),
        posted_by_id=posted_by_id,
        commit=False,
    )
    deposit.journal_entry_id = entry.id
    await db.commit()
    await db.refresh(deposit)
    return deposit


async def return_deposit(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    deposit: SecurityDeposit,
    *,
    returned_amount: Decimal = Decimal("0"),
    forfeited_amount: Decimal = Decimal("0"),
    returned_date: date | None = None,
    posted_by_id: uuid.UUID | None = None,
) -> SecurityDeposit:
    """Return and/or forfeit a held deposit, reversing the liability.

    Posts ``Dr Security Deposits Held`` for the total settled, crediting Cash for
    the amount returned to the resident and Forfeited Deposit Income for any
    amount kept by the org.
    """
    if deposit.status in ("returned", "forfeited"):
        raise RentError("This deposit has already been settled.")
    returned_amount = _q(returned_amount)
    forfeited_amount = _q(forfeited_amount)
    total = _q(returned_amount + forfeited_amount)
    if total <= 0:
        raise RentError("Provide a returned and/or forfeited amount greater than zero.")
    remaining = _q(deposit.amount - deposit.returned_amount - deposit.forfeited_amount)
    if total > remaining:
        raise RentError("Return/forfeit exceeds the remaining held deposit.")

    await ensure_rent_accounts(db, organization_id)
    account_map = await gl_service.get_account_map(db, organization_id)
    cash = account_map["Cash"]
    held = account_map["Security Deposits Held"]
    forfeit_income = account_map["Forfeited Deposit Income"]

    lines = [{"account_id": held.id, "debit": total, "credit": 0}]
    if returned_amount > 0:
        lines.append({"account_id": cash.id, "debit": 0, "credit": returned_amount})
    if forfeited_amount > 0:
        lines.append(
            {"account_id": forfeit_income.id, "debit": 0, "credit": forfeited_amount}
        )

    settle_date = returned_date or date.today()
    entry = await gl_service.create_journal_entry(
        db,
        organization_id,
        entry_date=settle_date,
        lines=lines,
        memo=f"Security deposit settlement (deposit {deposit.id})",
        source=DEPOSIT_GL_SOURCE,
        source_ref=_deposit_return_ref(deposit),
        posted_by_id=posted_by_id,
        commit=False,
    )
    deposit.return_journal_entry_id = entry.id
    deposit.returned_amount = _q(deposit.returned_amount + returned_amount)
    deposit.forfeited_amount = _q(deposit.forfeited_amount + forfeited_amount)
    deposit.returned_date = settle_date
    settled = _q(deposit.returned_amount + deposit.forfeited_amount)
    if settled >= _q(deposit.amount):
        deposit.status = "forfeited" if deposit.forfeited_amount == deposit.amount else "returned"
    else:
        deposit.status = "partially_returned"
    await db.commit()
    await db.refresh(deposit)
    return deposit
