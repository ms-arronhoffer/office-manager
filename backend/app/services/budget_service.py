"""Budget-vs-actual service layer (Phase 1.4).

Computes actuals live from the general ledger and pairs them with planned
``Budget`` amounts to produce variance rows. Actuals are summed on each
account's normal balance side so a positive variance always means "over plan"
for expenses and "under plan" for revenue is surfaced consistently via the sign
of ``variance = actual - budget``.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.budget import Budget, BudgetLine
from app.models.general_ledger import (
    DEBIT_NORMAL_TYPES,
    JournalEntry,
    JournalEntryLine,
)

TWO = Decimal("0.01")


def _q(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(TWO, rounding=ROUND_HALF_UP)


def fiscal_year_bounds(year: int, as_of: date | None = None) -> tuple[date, date]:
    """Return the (start, end) date window for a fiscal year.

    ``as_of`` clamps the end date so partial-year variance can be computed; it is
    ignored when it falls outside the fiscal year.
    """
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    if as_of is not None and start <= as_of <= end:
        end = as_of
    return start, end


async def actuals_by_account(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    start: date,
    end: date,
) -> dict[uuid.UUID, Decimal]:
    """Sum posted GL activity per account within [start, end] on its normal side."""
    stmt = (
        select(JournalEntry)
        .where(
            JournalEntry.organization_id == organization_id,
            JournalEntry.entry_date >= start,
            JournalEntry.entry_date <= end,
        )
        .options(selectinload(JournalEntry.lines).selectinload(JournalEntryLine.account))
    )
    entries = (await db.execute(stmt)).scalars().unique().all()

    totals: dict[uuid.UUID, Decimal] = {}
    for entry in entries:
        for line in entry.lines:
            acct = line.account
            if acct.type in DEBIT_NORMAL_TYPES:
                signed = _q(line.debit) - _q(line.credit)
            else:
                signed = _q(line.credit) - _q(line.debit)
            totals[acct.id] = _q(totals.get(acct.id, Decimal("0.00")) + signed)
    return totals


def _variance_pct(actual: Decimal, budget: Decimal) -> float | None:
    if budget == 0:
        return None
    return float((_q(actual - budget) / budget * 100).quantize(TWO, rounding=ROUND_HALF_UP))


async def budget_vs_actual(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    budget: Budget,
    *,
    as_of: date | None = None,
) -> dict:
    """Return budget-vs-actual rows for every account referenced by the budget."""
    start, end = fiscal_year_bounds(budget.fiscal_year, as_of)
    actuals = await actuals_by_account(db, organization_id, start, end)

    rows: list[dict] = []
    total_budget = Decimal("0.00")
    total_actual = Decimal("0.00")
    for line in budget.lines:
        acct = line.account
        planned = _q(line.amount)
        actual = _q(actuals.get(acct.id, Decimal("0.00")))
        variance = _q(actual - planned)
        total_budget = _q(total_budget + planned)
        total_actual = _q(total_actual + actual)
        rows.append(
            {
                "account_id": acct.id,
                "code": acct.code,
                "name": acct.name,
                "type": acct.type,
                "budget": planned,
                "actual": actual,
                "variance": variance,
                "variance_pct": _variance_pct(actual, planned),
            }
        )

    rows.sort(key=lambda r: r["code"])
    return {
        "budget_id": budget.id,
        "name": budget.name,
        "fiscal_year": budget.fiscal_year,
        "as_of": end,
        "rows": rows,
        "total_budget": total_budget,
        "total_actual": total_actual,
        "total_variance": _q(total_actual - total_budget),
    }


async def get_budget(
    db: AsyncSession, budget_id: uuid.UUID, organization_id: uuid.UUID | None
) -> Budget | None:
    """Load a budget with its lines and each line's account eagerly."""
    return (
        await db.execute(
            select(Budget)
            .where(
                Budget.id == budget_id,
                Budget.organization_id == organization_id,
            )
            .options(selectinload(Budget.lines).selectinload(BudgetLine.account))
        )
    ).scalar_one_or_none()
