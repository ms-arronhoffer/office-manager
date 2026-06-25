"""Lease-lifecycle accounting service layer (Phase 4).

Holds the pure ASC 842 / IFRS 16 remeasurement computation plus the persistence
helpers used by the ``/api/v1/lifecycle`` router:

  - ``compute_lifecycle_event`` — pure function turning a lease's pre-event
    carrying amounts and a set of revised terms into the remeasured liability,
    the ROU-asset adjustment, and any gain/loss.
  - ``derive_pre_event_carrying`` — read the liability and ROU carrying amounts
    at the effective date straight off the lease's original ASC 842 schedule.
  - ``post_event_to_gl`` — post a finalized event's remeasurement / gain / loss
    into the general ledger.

The remeasurement math follows standard practice:

  - **Modification / renewal** — the liability is remeasured to the present value
    of the revised remaining payments at a revised discount rate. The ROU asset
    is adjusted by the same amount; if a decrease in the liability exceeds the
    ROU carrying amount, the excess is recognised in P&L (a gain).
  - **Partial termination** — the liability and ROU are reduced in proportion to
    the decrease in scope; the difference between the two reductions is a
    gain/loss. Any remaining terms can then be remeasured.
  - **Full termination** — the remaining liability and ROU are derecognised; the
    difference, net of any cash penalty, is the gain/loss.

For every event type the gain/loss equals the figure that balances the journal
entry, so the GL posting is always balanced:

    gain_loss = (pre_liability - post_liability)
              + (post_rou - pre_rou)
              - termination_penalty
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lease_lifecycle import EVENT_TYPES, LeaseLifecycleEvent

TWO = Decimal("0.01")


class LifecycleError(ValueError):
    """Raised for lease-lifecycle rule violations."""


def _q(value) -> Decimal:
    """Round to 2 decimal places (currency)."""
    return Decimal(str(value)).quantize(TWO, rounding=ROUND_HALF_UP)


def _d(value) -> Decimal | None:
    """Coerce an optional numeric value to Decimal (None stays None)."""
    if value is None:
        return None
    return Decimal(str(value))


def _floor_zero(value: Decimal) -> Decimal:
    """Clamp a currency amount to zero (a negative ROU balance is not carried)."""
    return value if value > 0 else Decimal("0")


# ---------------------------------------------------------------------------
# Present value of a revised payment stream
# ---------------------------------------------------------------------------

def _is_payment_period(t: int, frequency: str) -> bool:
    """Return True if period t (1-indexed) is a payment period."""
    if frequency == "quarterly":
        return t % 3 == 0
    if frequency == "annually":
        return t % 12 == 0
    return True  # monthly / fallback


def present_value_remaining(
    *,
    payment_amount,
    months: int,
    annual_rate,
    frequency: str = "monthly",
    annual_escalation=0,
) -> Decimal:
    """Present value of ``months`` of revised payments at ``annual_rate``.

    Mirrors the discounting convention of the initial ASC 842 schedule: payments
    are discounted at a compound monthly rate derived from the annual rate, and
    escalation is applied per full elapsed year.
    """
    payment = _d(payment_amount)
    rate = _d(annual_rate)
    escalation = _d(annual_escalation) or Decimal("0")
    if payment is None or rate is None:
        raise LifecycleError(
            "new_payment_amount and new_incremental_borrowing_rate are required "
            "to remeasure the lease liability."
        )
    if months <= 0:
        raise LifecycleError("remaining_term_months must be a positive integer.")

    monthly_rate = Decimal(str((1 + float(rate)) ** (1 / 12) - 1))
    pv = Decimal("0")
    for t in range(1, months + 1):
        if not _is_payment_period(t, frequency):
            continue
        year_index = (t - 1) // 12
        factor = Decimal(str((1 + float(escalation)) ** year_index))
        pmt = _q(payment * factor)
        denominator = Decimal(str((1 + float(monthly_rate)) ** t))
        pv += _q(pmt / denominator)
    return _q(pv)


# ---------------------------------------------------------------------------
# Pure remeasurement computation
# ---------------------------------------------------------------------------

def compute_lifecycle_event(
    *,
    event_type: str,
    pre_liability,
    pre_rou,
    new_payment_amount=None,
    new_payment_frequency: str | None = None,
    new_annual_escalation_rate=None,
    new_incremental_borrowing_rate=None,
    remaining_term_months: int | None = None,
    remaining_percentage=None,
    termination_penalty=0,
) -> dict:
    """Compute the remeasurement result for a single lifecycle event.

    Returns a dict with ``revised_liability``, ``liability_adjustment``,
    ``rou_adjustment``, ``post_liability``, ``post_rou`` and ``gain_loss``.
    """
    if event_type not in EVENT_TYPES:
        raise LifecycleError(
            f"Invalid event_type '{event_type}'. Must be one of: "
            f"{', '.join(sorted(EVENT_TYPES))}."
        )

    pre_liab = _q(pre_liability or 0)
    pre_rou_amt = _q(pre_rou or 0)
    penalty = _q(termination_penalty or 0)
    if pre_liab < 0 or pre_rou_amt < 0:
        raise LifecycleError("Pre-event liability and ROU amounts cannot be negative.")
    if penalty < 0:
        raise LifecycleError("termination_penalty cannot be negative.")

    def _remeasured_liability() -> Decimal:
        return present_value_remaining(
            payment_amount=new_payment_amount,
            months=int(remaining_term_months) if remaining_term_months else 0,
            annual_rate=new_incremental_borrowing_rate,
            frequency=new_payment_frequency or "monthly",
            annual_escalation=new_annual_escalation_rate or 0,
        )

    if event_type in ("modification", "renewal"):
        revised_liability = _remeasured_liability()
        liability_adjustment = _q(revised_liability - pre_liab)
        # ROU moves with the liability; a decrease below zero is a P&L gain.
        tentative_rou = _q(pre_rou_amt + liability_adjustment)
        post_rou = _floor_zero(tentative_rou)
        post_liability = revised_liability

    elif event_type == "full_termination":
        revised_liability = Decimal("0")
        post_liability = Decimal("0")
        post_rou = Decimal("0")

    else:  # partial_termination
        share = _d(remaining_percentage)
        if share is None or share <= 0 or share >= 1:
            raise LifecycleError(
                "partial_termination requires remaining_percentage strictly "
                "between 0 and 1 (the fraction of the lease retained)."
            )
        liability_after = _q(pre_liab * share)
        rou_after = _q(pre_rou_amt * share)
        if new_incremental_borrowing_rate is not None and new_payment_amount is not None:
            # Remeasure the retained portion at revised terms; the remeasurement
            # delta adjusts the ROU asset (no additional P&L).
            revised_liability = _remeasured_liability()
            remeasure_delta = _q(revised_liability - liability_after)
            tentative_rou = _q(rou_after + remeasure_delta)
            post_rou = _floor_zero(tentative_rou)
            post_liability = revised_liability
        else:
            revised_liability = liability_after
            post_liability = liability_after
            post_rou = rou_after

    liability_adjustment = _q(post_liability - pre_liab)
    rou_adjustment = _q(post_rou - pre_rou_amt)
    # Balancing figure: positive => gain, negative => loss.
    gain_loss = _q((pre_liab - post_liability) + (post_rou - pre_rou_amt) - penalty)

    return {
        "revised_liability": _q(revised_liability),
        "liability_adjustment": liability_adjustment,
        "rou_adjustment": rou_adjustment,
        "post_liability": _q(post_liability),
        "post_rou": _q(post_rou),
        "gain_loss": gain_loss,
        "termination_penalty": penalty,
    }


def apply_computation(event: LeaseLifecycleEvent, result: dict) -> None:
    """Copy computed remeasurement totals onto a lifecycle-event ORM instance."""
    event.revised_liability = result["revised_liability"]
    event.liability_adjustment = result["liability_adjustment"]
    event.rou_adjustment = result["rou_adjustment"]
    event.post_liability = result["post_liability"]
    event.post_rou = result["post_rou"]
    event.gain_loss = result["gain_loss"]


# ---------------------------------------------------------------------------
# Deriving pre-event carrying amounts from the original schedule
# ---------------------------------------------------------------------------

def derive_pre_event_carrying(lease, effective_date: date) -> tuple[Decimal, Decimal]:
    """Return ``(pre_liability, pre_rou)`` at ``effective_date`` from the lease's
    original ASC 842 / IFRS 16 schedule.

    Raises :class:`LifecycleError` if the lease lacks the fields needed to build
    a schedule, or if the effective date is on/before commencement.
    """
    from app.services.lease_accounting import (
        _months_between,
        compute_lease_accounting,
    )

    try:
        data = compute_lease_accounting(lease, include_journal_entries=False)
    except ValueError as e:
        raise LifecycleError(str(e))
    if data.get("exempt"):
        raise LifecycleError(
            "Lease is exempt from ROU/Liability recognition; no carrying amounts "
            "to remeasure."
        )

    schedule = data["schedule"]
    commencement = lease.lease_commencement_date
    k = _months_between(commencement, effective_date)
    if k <= 0:
        # On/before commencement: full initial amounts.
        return _q(data["initial_lease_liability"]), _q(data["initial_rou_asset"])
    if k >= len(schedule):
        last = schedule[-1]
        return _q(last["closing_liability"]), _q(last["rou_carrying_value"])
    # Liability at the date is the opening balance of the next period; ROU is the
    # carrying value at the end of the most recently completed period.
    pre_liability = schedule[k]["opening_liability"]
    pre_rou = schedule[k - 1]["rou_carrying_value"]
    return _q(pre_liability), _q(pre_rou)


# ---------------------------------------------------------------------------
# GL posting
# ---------------------------------------------------------------------------

# Lifecycle-specific accounts required to post a remeasurement / termination.
LIFECYCLE_ACCOUNTS: list[tuple[str, str, str]] = [
    ("4200", "Lease Termination Gain", "revenue"),
    ("6300", "Lease Termination Loss", "expense"),
]


async def post_event_to_gl(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    event: LeaseLifecycleEvent,
    *,
    posted_by_id: uuid.UUID | None = None,
):
    """Post a finalized lifecycle event's remeasurement into the GL.

    The entry adjusts the Lease Liability and Right-of-Use Asset to their
    post-event carrying amounts, records any cash termination penalty, and books
    the balancing gain or loss. Re-posting first removes any prior
    ``lifecycle``-sourced entry for the event so the ledger is not
    double-counted. An event with no net effect posts nothing.
    """
    from app.services import gl_service

    if event.status != "finalized":
        raise LifecycleError("Only a finalized event can be posted to the GL.")

    await gl_service.seed_default_accounts(db, organization_id)
    await gl_service.ensure_accounts(db, organization_id, LIFECYCLE_ACCOUNTS)
    account_map = await gl_service.get_account_map(db, organization_id)

    # Idempotent re-post: drop any prior lifecycle-sourced entry for this event.
    await gl_service.delete_entries_by_source(
        db, organization_id, source="lifecycle", source_ref=str(event.id), commit=False
    )
    event.journal_entry_id = None

    pre_liab = _q(event.pre_liability)
    pre_rou = _q(event.pre_rou)
    post_liab = _q(event.post_liability)
    post_rou = _q(event.post_rou)
    penalty = _q(event.termination_penalty)

    liability = account_map["Lease Liability"]
    rou = account_map["Right-of-Use Asset"]
    cash = account_map["Cash"]
    gain = account_map["Lease Termination Gain"]
    loss = account_map["Lease Termination Loss"]

    lines: list[dict] = []

    # Lease Liability movement (a decrease is a debit; an increase a credit).
    liab_debit = _q(pre_liab - post_liab)
    if liab_debit > 0:
        lines.append({"account_id": liability.id, "debit": liab_debit, "credit": 0})
    elif liab_debit < 0:
        lines.append({"account_id": liability.id, "debit": 0, "credit": _q(-liab_debit)})

    # Right-of-Use Asset movement (an increase is a debit; a decrease a credit).
    rou_debit = _q(post_rou - pre_rou)
    if rou_debit > 0:
        lines.append({"account_id": rou.id, "debit": rou_debit, "credit": 0})
    elif rou_debit < 0:
        lines.append({"account_id": rou.id, "debit": 0, "credit": _q(-rou_debit)})

    # Cash termination penalty paid.
    if penalty > 0:
        lines.append({"account_id": cash.id, "debit": 0, "credit": penalty})

    # Balancing gain or loss.
    gain_loss = _q(event.gain_loss)
    if gain_loss > 0:
        lines.append({"account_id": gain.id, "debit": 0, "credit": gain_loss})
    elif gain_loss < 0:
        lines.append({"account_id": loss.id, "debit": _q(-gain_loss), "credit": 0})

    if not lines:
        await db.commit()
        return None

    entry = await gl_service.create_journal_entry(
        db,
        organization_id,
        entry_date=event.effective_date,
        lines=lines,
        memo=f"Lease {event.event_type} (lease {event.lease_id})",
        source="lifecycle",
        source_ref=str(event.id),
        posted_by_id=posted_by_id,
        commit=False,
    )
    event.journal_entry_id = entry.id
    event.finalized_at = event.finalized_at or datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(entry)
    return entry
