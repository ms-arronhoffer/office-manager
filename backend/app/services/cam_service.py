"""CAM (common-area-maintenance) reconciliation service layer (Phase 3).

Holds the pure US-commercial recovery computation plus the persistence helpers
used by the `/api/v1/cam` router:

  - ``compute_cam_reconciliation`` — pure function turning an expense pool and a
    set of recovery terms into a tenant obligation and true-up/credit balance.
  - ``resolve_pro_rata_share`` — derive the tenant share from square footage.
  - ``lines_from_operating_expenses`` — seed reconciliation lines from the
    existing :class:`OperatingExpense` actuals for a lease-year.
  - ``post_reconciliation_to_gl`` — post a finalized reconciliation's true-up or
    credit into the general ledger.

The recovery math follows standard commercial-lease practice:

  1. Variable expenses are *grossed up* to the occupancy standard so that
     occupancy-sensitive costs reflect a fully-occupied building.
  2. The tenant pays its *pro-rata share* of the grossed-up pool, split into
     controllable and non-controllable buckets.
  3. Controllable expenses are limited by an annual *cap* relative to a base
     year (cumulative-compounded, cumulative-simple, or non-cumulative).
  4. A *base-year stop* or *expense stop* reduces the recoverable amount.
  5. The recoverable amount net of estimates already paid yields the balance:
     positive means the tenant owes a true-up, negative means a credit is due.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cam_reconciliation import (
    CAP_TYPES,
    CamReconciliation,
    CamReconciliationLine,
)
from app.models.operating_expense import OperatingExpense

TWO = Decimal("0.01")

# Categories that are conventionally non-controllable (pass-through, uncapped).
NON_CONTROLLABLE_CATEGORIES = {"taxes", "insurance", "utilities"}
# Categories conventionally grossed up to the occupancy standard.
GROSS_UP_CATEGORIES = {"cam", "utilities"}


class CamError(ValueError):
    """Raised for CAM reconciliation rule violations."""


def _q(value) -> Decimal:
    """Round to 2 decimal places (currency)."""
    return Decimal(str(value)).quantize(TWO, rounding=ROUND_HALF_UP)


def _d(value) -> Decimal | None:
    """Coerce an optional numeric value to Decimal (None stays None)."""
    if value is None:
        return None
    return Decimal(str(value))


def resolve_pro_rata_share(
    pro_rata_share, rentable_sqft, building_sqft
) -> Decimal:
    """Return the tenant pro-rata share as a fraction.

    Uses the explicit ``pro_rata_share`` when given, otherwise derives it from
    ``rentable_sqft / building_sqft``. Raises :class:`CamError` if neither a
    share nor a usable square-footage pair is available.
    """
    share = _d(pro_rata_share)
    if share is not None:
        if share < 0 or share > 1:
            raise CamError("pro_rata_share must be a fraction between 0 and 1.")
        return share
    rentable = _d(rentable_sqft)
    building = _d(building_sqft)
    if rentable is not None and building is not None and building > 0:
        return rentable / building
    raise CamError(
        "Provide pro_rata_share, or both rentable_sqft and building_sqft, "
        "to determine the tenant's share."
    )


def _cap_factor(cap_type: str, cap_percent: Decimal, periods: int) -> Decimal:
    """Growth factor applied to the controllable cap base over ``periods`` years."""
    if periods <= 0:
        return Decimal("1")
    if cap_type == "cumulative":
        return Decimal("1") + cap_percent * Decimal(periods)
    if cap_type == "non_cumulative":
        # Each year is capped at cap_percent over the base (no carry-forward).
        return Decimal("1") + cap_percent
    # Default and "cumulative_compounded".
    return (Decimal("1") + cap_percent) ** periods


def compute_cam_reconciliation(
    *,
    lines: list[dict],
    pro_rata_share: Decimal,
    year: int,
    gross_up_percent=None,
    occupancy_percent=None,
    base_year_amount=None,
    expense_stop_psf=None,
    rentable_sqft=None,
    cap_percent=None,
    cap_type=None,
    cap_base_year=None,
    cap_base_amount=None,
    estimated_paid=0,
) -> dict:
    """Compute a CAM reconciliation statement.

    ``lines`` is a list of dicts each with ``category``, ``actual_amount`` and
    the booleans ``controllable`` and ``gross_up_eligible``. Returns a dict with
    per-line grossed-up amounts and all statement totals (see module docstring).
    """
    share = _d(pro_rata_share)
    if share is None:
        raise CamError("pro_rata_share is required.")

    gross_up = _d(gross_up_percent)
    occupancy = _d(occupancy_percent)
    cap_pct = _d(cap_percent)
    cap_base_amt = _d(cap_base_amount)
    estimated = _q(estimated_paid or 0)

    if cap_type is not None and cap_type not in CAP_TYPES:
        raise CamError(
            f"Invalid cap_type '{cap_type}'. Must be one of: {', '.join(sorted(CAP_TYPES))}."
        )

    # --- Step 1: gross up eligible (variable) expenses ---
    gross_up_factor = Decimal("1")
    if (
        gross_up is not None
        and occupancy is not None
        and occupancy > 0
        and occupancy < gross_up
    ):
        gross_up_factor = gross_up / occupancy

    computed_lines: list[dict] = []
    controllable_pool = Decimal("0")
    noncontrollable_pool = Decimal("0")
    for raw in lines:
        actual = _d(raw.get("actual_amount") or 0) or Decimal("0")
        controllable = bool(raw.get("controllable", True))
        gross_eligible = bool(raw.get("gross_up_eligible", False))
        grossed = _q(actual * gross_up_factor) if gross_eligible else _q(actual)
        computed_lines.append(
            {
                "category": raw.get("category"),
                "controllable": controllable,
                "gross_up_eligible": gross_eligible,
                "actual_amount": _q(actual),
                "grossed_up_amount": grossed,
            }
        )
        if controllable:
            controllable_pool += grossed
        else:
            noncontrollable_pool += grossed

    controllable_pool = _q(controllable_pool)
    noncontrollable_pool = _q(noncontrollable_pool)
    total_pool = _q(controllable_pool + noncontrollable_pool)

    # --- Step 2: tenant pro-rata share ---
    tenant_controllable = _q(controllable_pool * share)
    tenant_noncontrollable = _q(noncontrollable_pool * share)
    tenant_share_amount = _q(tenant_controllable + tenant_noncontrollable)

    # --- Step 3: controllable cap ---
    cap_applied = Decimal("0")
    capped_controllable = tenant_controllable
    if (
        cap_pct is not None
        and cap_base_amt is not None
        and cap_base_year is not None
    ):
        periods = year - int(cap_base_year)
        if periods < 0:
            raise CamError("cap_base_year cannot be after the reconciliation year.")
        factor = _cap_factor(cap_type or "cumulative_compounded", cap_pct, periods)
        ceiling = _q(cap_base_amt * factor)
        if tenant_controllable > ceiling:
            capped_controllable = ceiling
            cap_applied = _q(tenant_controllable - ceiling)

    recoverable_before_offset = _q(capped_controllable + tenant_noncontrollable)

    # --- Step 4: base-year stop or expense stop ---
    offset = Decimal("0")
    base_year_amt = _d(base_year_amount)
    stop_psf = _d(expense_stop_psf)
    rentable = _d(rentable_sqft)
    if base_year_amt is not None:
        offset = _q(base_year_amt)
    elif stop_psf is not None and rentable is not None:
        offset = _q(stop_psf * rentable)

    recoverable = recoverable_before_offset - offset
    if recoverable < 0:
        recoverable = Decimal("0")
    recoverable = _q(recoverable)

    # --- Step 5: balance vs estimates paid ---
    balance_due = _q(recoverable - estimated)

    return {
        "lines": computed_lines,
        "pro_rata_share": share,
        "total_pool": total_pool,
        "controllable_pool": controllable_pool,
        "noncontrollable_pool": noncontrollable_pool,
        "tenant_share_amount": tenant_share_amount,
        "cap_applied": cap_applied,
        "offset_amount": offset,
        "recoverable_amount": recoverable,
        "balance_due": balance_due,
        "estimated_paid": estimated,
    }


def default_line_flags(category: str) -> tuple[bool, bool]:
    """Return ``(controllable, gross_up_eligible)`` defaults for a category."""
    cat = (category or "").strip().lower()
    controllable = cat not in NON_CONTROLLABLE_CATEGORIES
    gross_up_eligible = cat in GROSS_UP_CATEGORIES
    return controllable, gross_up_eligible


async def lines_from_operating_expenses(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    lease_id: uuid.UUID,
    year: int,
) -> list[dict]:
    """Build reconciliation line inputs from a lease-year's operating expenses."""
    rows = (
        await db.execute(
            select(OperatingExpense).where(
                OperatingExpense.organization_id == organization_id,
                OperatingExpense.lease_id == lease_id,
                OperatingExpense.year == year,
            )
        )
    ).scalars().all()
    result: list[dict] = []
    for row in rows:
        if row.actual is None:
            continue
        controllable, gross_up_eligible = default_line_flags(row.category)
        result.append(
            {
                "category": row.category,
                "actual_amount": row.actual,
                "controllable": controllable,
                "gross_up_eligible": gross_up_eligible,
            }
        )
    return result


def apply_computation(recon: CamReconciliation, result: dict) -> None:
    """Copy computed totals and lines onto a reconciliation ORM instance."""
    recon.pro_rata_share = result["pro_rata_share"]
    recon.total_pool = result["total_pool"]
    recon.controllable_pool = result["controllable_pool"]
    recon.noncontrollable_pool = result["noncontrollable_pool"]
    recon.tenant_share_amount = result["tenant_share_amount"]
    recon.cap_applied = result["cap_applied"]
    recon.offset_amount = result["offset_amount"]
    recon.recoverable_amount = result["recoverable_amount"]
    recon.balance_due = result["balance_due"]

    recon.lines = [
        CamReconciliationLine(
            line_number=idx,
            category=line["category"],
            controllable=line["controllable"],
            gross_up_eligible=line["gross_up_eligible"],
            actual_amount=line["actual_amount"],
            grossed_up_amount=line["grossed_up_amount"],
        )
        for idx, line in enumerate(result["lines"], start=1)
    ]


# CAM-specific accounts required to post a reconciliation to the GL.
CAM_ACCOUNTS: list[tuple[str, str, str]] = [
    ("1200", "CAM Receivable", "asset"),
    ("2100", "CAM Refund Payable", "liability"),
    ("4100", "CAM Recovery Income", "revenue"),
]


async def post_reconciliation_to_gl(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    recon: CamReconciliation,
    *,
    posted_by_id: uuid.UUID | None = None,
):
    """Post a finalized reconciliation's true-up or credit into the GL.

    A positive balance (tenant owes) debits CAM Receivable and credits CAM
    Recovery Income. A negative balance (credit due to tenant) reverses income
    and records a CAM Refund Payable. A zero balance posts nothing.

    Re-posting first removes any prior ``cam``-sourced entry for the
    reconciliation so the ledger is not double-counted.
    """
    from app.services import gl_service

    if recon.status != "finalized":
        raise CamError("Only a finalized reconciliation can be posted to the GL.")

    await gl_service.ensure_accounts(db, organization_id, CAM_ACCOUNTS)
    account_map = await gl_service.get_account_map(db, organization_id)

    # Idempotent re-post: drop any prior cam-sourced entry for this statement.
    await gl_service.delete_entries_by_source(
        db, organization_id, source="cam", source_ref=str(recon.id), commit=False
    )
    recon.journal_entry_id = None

    balance = _q(recon.balance_due)
    if balance == 0:
        await db.commit()
        return None

    receivable = account_map["CAM Receivable"]
    income = account_map["CAM Recovery Income"]
    refund_payable = account_map["CAM Refund Payable"]

    if balance > 0:
        # Tenant owes a true-up: recognise recovery income and a receivable.
        lines = [
            {"account_id": receivable.id, "debit": balance, "credit": 0},
            {"account_id": income.id, "debit": 0, "credit": balance},
        ]
    else:
        # Credit due to tenant: reverse income and record a refund payable.
        amount = _q(-balance)
        lines = [
            {"account_id": income.id, "debit": amount, "credit": 0},
            {"account_id": refund_payable.id, "debit": 0, "credit": amount},
        ]

    entry = await gl_service.create_journal_entry(
        db,
        organization_id,
        entry_date=date(recon.year, 12, 31),
        lines=lines,
        memo=f"CAM reconciliation {recon.year} (lease {recon.lease_id})",
        source="cam",
        source_ref=str(recon.id),
        posted_by_id=posted_by_id,
        commit=False,
    )
    recon.journal_entry_id = entry.id
    recon.finalized_at = recon.finalized_at or datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(entry)
    return entry
