"""Self-storage domain service (org-as-operator).

Business logic for the self-storage category: unit occupancy derivation, the
move-in / move-out lifecycle, rate changes and scheduled rent increases, the
delinquency → lien → auction workflow, and recurring billing that posts through
the **shared AR/GL** (mirroring ``rent_service``) rather than a parallel ledger.

Because storage tenants are ordinary :class:`~app.models.resident.Resident`
records, billing reuses ``rent_service.get_or_create_customer_for_resident`` to
bind a tenant to an AR :class:`~app.models.customer_invoice.Customer`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.customer_invoice import CustomerInvoice, CustomerInvoiceLine
from app.models.general_ledger import GLAccount
from app.models.resident import Resident
from app.models.self_storage import (
    STORAGE_ACTIVE_STATUSES,
    STORAGE_LIEN_STEPS,
    StorageAgreement,
    StorageAgreementOccupant,
    StorageCharge,
    StorageLienEvent,
    StorageUnit,
)
from app.services import ar_service, gl_service, rent_service

TWO = Decimal("0.01")

# Provenance tag carried on generated storage AR invoices.
STORAGE_INVOICE_SOURCE = "self_storage"

# Storage-specific revenue accounts ensured present before posting.
STORAGE_ACCOUNTS: list[tuple[str, str, str]] = [
    ("4100", "Storage Rental Income", "revenue"),
    ("4110", "Tenant Insurance Income", "revenue"),
    ("4120", "Storage Late Fee Income", "revenue"),
]


class SelfStorageError(ValueError):
    """Raised for self-storage rule violations."""


def _q(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(TWO, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Occupancy derivation
# ---------------------------------------------------------------------------

async def assert_no_active_overlap(
    db: AsyncSession,
    unit_id: uuid.UUID,
    *,
    exclude_agreement_id: uuid.UUID | None = None,
) -> None:
    """Ensure a unit has no other active agreement (a unit is single-tenant)."""
    stmt = select(StorageAgreement).where(
        StorageAgreement.unit_id == unit_id,
        StorageAgreement.is_deleted.is_(False),
        StorageAgreement.status.in_(STORAGE_ACTIVE_STATUSES),
    )
    if exclude_agreement_id is not None:
        stmt = stmt.where(StorageAgreement.id != exclude_agreement_id)
    conflict = (await db.execute(stmt)).scalars().first()
    if conflict is not None:
        raise SelfStorageError(
            "This unit already has an active rental agreement."
        )


async def sync_unit_status(
    db: AsyncSession,
    unit_id: uuid.UUID,
    organization_id: uuid.UUID | None,
) -> StorageUnit | None:
    """Recompute and persist a unit's occupancy status from its agreements.

    Manual states (``maintenance``, ``overlocked``, ``lien``, ``auction``,
    ``reserved``) are preserved — only the available/occupied axis is derived.
    """
    unit = (
        await db.execute(
            select(StorageUnit).where(
                StorageUnit.id == unit_id,
                StorageUnit.organization_id == organization_id,
                StorageUnit.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if unit is None:
        return None
    if unit.status in ("maintenance", "overlocked", "lien", "auction", "reserved"):
        return unit
    active = (
        await db.execute(
            select(StorageAgreement.id).where(
                StorageAgreement.unit_id == unit_id,
                StorageAgreement.is_deleted.is_(False),
                StorageAgreement.status.in_(STORAGE_ACTIVE_STATUSES),
            )
        )
    ).first()
    unit.status = "occupied" if active is not None else "available"
    return unit


def primary_resident(agreement: StorageAgreement) -> Resident | None:
    """Return the primary occupant (or first occupant) of an agreement."""
    occupants = list(agreement.occupants or [])
    if not occupants:
        return None
    primary = next((o for o in occupants if o.is_primary), None)
    chosen = primary or occupants[0]
    return chosen.resident


async def _load_agreement(
    db: AsyncSession, organization_id: uuid.UUID | None, agreement_id: uuid.UUID
) -> StorageAgreement:
    agreement = (
        await db.execute(
            select(StorageAgreement)
            .where(
                StorageAgreement.id == agreement_id,
                StorageAgreement.organization_id == organization_id,
            )
            .options(
                selectinload(StorageAgreement.occupants).selectinload(
                    StorageAgreementOccupant.resident
                ),
                selectinload(StorageAgreement.unit),
            )
        )
    ).scalar_one_or_none()
    if agreement is None:
        raise SelfStorageError("Storage agreement not found.")
    return agreement


# ---------------------------------------------------------------------------
# Move-in / move-out lifecycle
# ---------------------------------------------------------------------------

async def move_in(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    agreement_id: uuid.UUID,
    *,
    move_in_date: date | None = None,
) -> StorageAgreement:
    """Activate an agreement (move-in) and mark its unit occupied."""
    agreement = await _load_agreement(db, organization_id, agreement_id)
    if not agreement.occupants:
        raise SelfStorageError("Cannot move in an agreement with no occupants.")
    await assert_no_active_overlap(
        db, agreement.unit_id, exclude_agreement_id=agreement.id
    )
    agreement.status = "active"
    agreement.move_in_date = move_in_date or agreement.move_in_date or date.today()
    if agreement.start_date is None:
        agreement.start_date = agreement.move_in_date
    # Set the unit's in-place rate to the agreement rent on move-in.
    if agreement.unit is not None and agreement.rent_amount is not None:
        agreement.unit.in_place_rate = agreement.rent_amount
    await sync_unit_status(db, agreement.unit_id, organization_id)
    await db.commit()
    await db.refresh(agreement)
    return agreement


async def move_out(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    agreement_id: uuid.UUID,
    *,
    move_out_date: date | None = None,
) -> StorageAgreement:
    """End an agreement (move-out) and free its unit."""
    agreement = await _load_agreement(db, organization_id, agreement_id)
    agreement.status = "ended"
    agreement.move_out_date = move_out_date or date.today()
    if agreement.unit is not None:
        agreement.unit.in_place_rate = None
        agreement.unit.lock_state = "unlocked"
    await sync_unit_status(db, agreement.unit_id, organization_id)
    await db.commit()
    await db.refresh(agreement)
    return agreement


# ---------------------------------------------------------------------------
# Rate changes / scheduled rent increases
# ---------------------------------------------------------------------------

async def change_rate(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    agreement_id: uuid.UUID,
    new_rate: Decimal,
) -> StorageAgreement:
    """Change an agreement's in-place rent and mirror it on the unit."""
    agreement = await _load_agreement(db, organization_id, agreement_id)
    agreement.rent_amount = _q(new_rate)
    if agreement.unit is not None:
        agreement.unit.in_place_rate = agreement.rent_amount
    # Keep any active rent charge in sync.
    charges = (
        await db.execute(
            select(StorageCharge).where(
                StorageCharge.storage_agreement_id == agreement_id,
                StorageCharge.charge_type == "rent",
                StorageCharge.active.is_(True),
                StorageCharge.is_deleted.is_(False),
            )
        )
    ).scalars().all()
    for charge in charges:
        charge.amount = agreement.rent_amount
    await db.commit()
    await db.refresh(agreement)
    return agreement


async def apply_scheduled_increase(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    rate_plan,
    *,
    as_of: date | None = None,
) -> dict:
    """Apply a rate plan's scheduled increase to matching in-place agreements.

    Raises the rent of every active agreement whose unit matches the plan's
    ``size_tier`` (and facility, when the plan is facility-scoped) by the plan's
    flat amount or percentage. Idempotency is the caller's responsibility (the
    plan's effective date gates when this should run).
    """
    as_of = as_of or date.today()
    if rate_plan.increase_effective_date and rate_plan.increase_effective_date > as_of:
        return {"applied": 0}

    stmt = (
        select(StorageAgreement)
        .join(StorageUnit, StorageAgreement.unit_id == StorageUnit.id)
        .where(
            StorageAgreement.organization_id == organization_id,
            StorageAgreement.is_deleted.is_(False),
            StorageAgreement.status.in_(STORAGE_ACTIVE_STATUSES),
            StorageUnit.size_tier == rate_plan.size_tier,
        )
        .options(selectinload(StorageAgreement.unit))
    )
    if rate_plan.facility_id is not None:
        stmt = stmt.where(StorageUnit.facility_id == rate_plan.facility_id)
    agreements = (await db.execute(stmt)).scalars().all()

    applied = 0
    for agreement in agreements:
        base = agreement.rent_amount
        if base is None:
            continue
        if rate_plan.increase_amount is not None:
            new_rate = _q(base + rate_plan.increase_amount)
        elif rate_plan.increase_percent is not None:
            new_rate = _q(base * (Decimal("1") + rate_plan.increase_percent / Decimal("100")))
        else:
            continue
        agreement.rent_amount = new_rate
        if agreement.unit is not None:
            agreement.unit.in_place_rate = new_rate
        applied += 1
    await db.commit()
    return {"applied": applied}


# ---------------------------------------------------------------------------
# Delinquency → lien → auction workflow
# ---------------------------------------------------------------------------

# Allowed forward transitions of the lien lifecycle.
_LIEN_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "late": ("overlock", "redeemed", "released"),
    "overlock": ("lien_notice", "redeemed", "released"),
    "lien_notice": ("auction_scheduled", "redeemed", "released"),
    "auction_scheduled": ("auctioned", "redeemed", "released"),
    "auctioned": (),
    "redeemed": (),
    "released": (),
}

# Map a lien step to the agreement status it drives.
_STEP_TO_AGREEMENT_STATUS: dict[str, str] = {
    "late": "delinquent",
    "overlock": "delinquent",
    "lien_notice": "in_lien",
    "auction_scheduled": "in_lien",
    "auctioned": "auctioned",
    "redeemed": "active",
    "released": "active",
}

# Map a lien step to the unit status it drives (when applicable).
_STEP_TO_UNIT_STATUS: dict[str, str] = {
    "overlock": "overlocked",
    "lien_notice": "lien",
    "auction_scheduled": "lien",
    "auctioned": "auction",
}


async def _latest_lien_step(
    db: AsyncSession, organization_id: uuid.UUID | None, agreement_id: uuid.UUID
) -> str | None:
    """Return the most recent lien step for an agreement, read straight from the DB.

    Querying directly (rather than reading a possibly-stale ORM relationship
    collection) keeps the transition check correct even when the agreement was
    loaded earlier in the same session before newer events were recorded.
    """
    events = (
        await db.execute(
            select(StorageLienEvent)
            .where(
                StorageLienEvent.agreement_id == agreement_id,
                StorageLienEvent.organization_id == organization_id,
            )
            .order_by(StorageLienEvent.event_date, StorageLienEvent.created_at)
        )
    ).scalars().all()
    return events[-1].step if events else None


async def record_lien_step(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    agreement_id: uuid.UUID,
    step: str,
    *,
    event_date: date | None = None,
    amount_due: Decimal | None = None,
    notes: str | None = None,
    details: dict | None = None,
    created_by_id: uuid.UUID | None = None,
) -> StorageLienEvent:
    """Advance an agreement through the delinquency/lien/auction lifecycle.

    Validates that ``step`` is a legal transition from the agreement's current
    lien step, records a :class:`StorageLienEvent`, and drives the agreement
    (and, where applicable, the unit) status accordingly.
    """
    if step not in STORAGE_LIEN_STEPS:
        raise SelfStorageError(f"Unknown lien step: {step!r}")

    agreement = (
        await db.execute(
            select(StorageAgreement)
            .where(
                StorageAgreement.id == agreement_id,
                StorageAgreement.organization_id == organization_id,
            )
            .options(
                selectinload(StorageAgreement.unit),
            )
        )
    ).scalar_one_or_none()
    if agreement is None:
        raise SelfStorageError("Storage agreement not found.")

    current = await _latest_lien_step(db, organization_id, agreement_id)
    if current is None:
        if step != "late":
            raise SelfStorageError(
                "The delinquency lifecycle must start with a 'late' step."
            )
    else:
        allowed = _LIEN_TRANSITIONS.get(current, ())
        if step not in allowed:
            raise SelfStorageError(
                f"Cannot move from '{current}' to '{step}'."
            )

    event = StorageLienEvent(
        organization_id=organization_id,
        agreement_id=agreement_id,
        step=step,
        event_date=event_date or date.today(),
        amount_due=_q(amount_due) if amount_due is not None else None,
        notes=notes,
        details=details,
        created_by_id=created_by_id,
    )
    db.add(event)

    agreement.status = _STEP_TO_AGREEMENT_STATUS.get(step, agreement.status)
    unit = agreement.unit
    if unit is not None:
        if step in _STEP_TO_UNIT_STATUS:
            unit.status = _STEP_TO_UNIT_STATUS[step]
            if step == "overlock":
                unit.lock_state = "overlocked"
        elif step in ("redeemed", "released"):
            unit.status = "occupied"
            unit.lock_state = "tenant_locked"
        elif step == "auctioned":
            unit.lock_state = "unlocked"

    await db.commit()
    await db.refresh(event)
    return event


# ---------------------------------------------------------------------------
# Billing (shared AR/GL)
# ---------------------------------------------------------------------------

async def ensure_storage_accounts(
    db: AsyncSession, organization_id: uuid.UUID | None
) -> None:
    """Ensure the storage revenue GL accounts exist for the org."""
    await gl_service.seed_default_accounts(db, organization_id)
    await gl_service.ensure_accounts(db, organization_id, STORAGE_ACCOUNTS, commit=False)


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
        raise SelfStorageError(f"GL account with code {code} is not configured.")
    return acct


def _storage_source_ref(charge: StorageCharge, period_start: date) -> str:
    return f"storagecharge:{charge.id}:{period_start.isoformat()}"


def _due_date(period_start: date, day_of_month: int) -> date:
    return rent_service._due_date(period_start, day_of_month)


async def generate_storage_invoice(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    charge: StorageCharge,
    period_start: date,
    *,
    posted_by_id: uuid.UUID | None = None,
) -> CustomerInvoice | None:
    """Create, finalize, and post one storage invoice for a charge's period.

    Idempotent: returns ``None`` if an invoice for this charge+period exists.
    Bills the agreement's primary resident through the shared AR/GL.
    """
    source_ref = _storage_source_ref(charge, period_start)
    if await rent_service._invoice_exists(
        db, organization_id, STORAGE_INVOICE_SOURCE, source_ref
    ):
        return None

    agreement = await _load_agreement(db, organization_id, charge.storage_agreement_id)
    resident = primary_resident(agreement)
    if resident is None:
        raise SelfStorageError("Cannot bill an agreement with no occupants.")

    await ensure_storage_accounts(db, organization_id)
    customer = await rent_service.get_or_create_customer_for_resident(
        db, organization_id, resident
    )
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
        source=STORAGE_INVOICE_SOURCE,
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


def _due_periods(charge: StorageCharge, as_of: date) -> list[date]:
    """Return the first-of-month periods due for a charge up to ``as_of``."""
    start = charge.start_date or date.today().replace(day=1)
    period = date(start.year, start.month, 1)
    last = charge.last_billed_period
    periods: list[date] = []
    while period <= as_of:
        if charge.end_date and period > charge.end_date:
            break
        if last is None or period > last:
            periods.append(period)
        # advance one month
        if period.month == 12:
            period = date(period.year + 1, 1, 1)
        else:
            period = date(period.year, period.month + 1, 1)
    return periods


async def run_recurring_billing(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    *,
    as_of: date | None = None,
    posted_by_id: uuid.UUID | None = None,
) -> dict:
    """Generate all due storage invoices across active charges up to ``as_of``."""
    as_of = as_of or date.today()
    charges = (
        await db.execute(
            select(StorageCharge).where(
                StorageCharge.organization_id == organization_id,
                StorageCharge.active.is_(True),
                StorageCharge.is_deleted.is_(False),
            )
        )
    ).scalars().all()

    generated: list[uuid.UUID] = []
    for charge in charges:
        for period in _due_periods(charge, as_of):
            invoice = await generate_storage_invoice(
                db, organization_id, charge, period, posted_by_id=posted_by_id
            )
            if invoice is not None:
                generated.append(invoice.id)
    return {"generated": len(generated), "invoice_ids": [str(i) for i in generated]}


async def record_storage_payment(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    invoice: CustomerInvoice,
    amount: Decimal,
    *,
    method: str = "ach",
    receipt_date: date | None = None,
    reference: str | None = None,
    created_by_id: uuid.UUID | None = None,
) -> dict:
    """Record a payment against a storage invoice and post it to the GL."""
    from app.models.customer_invoice import CustomerReceipt

    amount = _q(amount)
    if amount <= 0:
        raise SelfStorageError("Payment amount must be positive.")

    receipt = CustomerReceipt(
        organization_id=organization_id,
        invoice_id=invoice.id,
        receipt_date=receipt_date or date.today(),
        amount=amount,
        method=method,
        reference=reference,
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
        "receipt_id": str(receipt.id),
        "amount": str(amount),
        "invoice_id": str(invoice.id),
    }


# ---------------------------------------------------------------------------
# Occupancy / revenue summary
# ---------------------------------------------------------------------------

async def occupancy_summary(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    *,
    facility_id: uuid.UUID | None = None,
) -> dict:
    """Build a physical/economic occupancy and revenue summary over units."""
    stmt = select(StorageUnit).where(
        StorageUnit.organization_id == organization_id,
        StorageUnit.is_deleted.is_(False),
    )
    if facility_id is not None:
        stmt = stmt.where(StorageUnit.facility_id == facility_id)
    units = (await db.execute(stmt)).scalars().all()

    total = len(units)
    occupied = sum(1 for u in units if u.status == "occupied")
    potential = sum((u.street_rate or Decimal("0")) for u in units)
    in_place = sum(
        (u.in_place_rate or Decimal("0")) for u in units if u.status == "occupied"
    )
    physical = (occupied / total * 100) if total else 0.0
    economic = (float(in_place / potential * 100) if potential else 0.0)
    return {
        "total_units": total,
        "occupied_units": occupied,
        "available_units": sum(1 for u in units if u.status == "available"),
        "physical_occupancy_pct": round(physical, 2),
        "economic_occupancy_pct": round(economic, 2),
        "potential_monthly_revenue": str(_q(potential)),
        "in_place_monthly_revenue": str(_q(in_place)),
        "currency": "USD",
    }
