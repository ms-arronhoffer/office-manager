"""Financial-statements service layer (Phase 6 + Phase 7).

Derives GAAP financial statements straight from the audit-grade general ledger
built in Phase 2, so they always tie back to the posted journal entries:

  - ``income_statement`` — revenue less expenses over a date range (profit &
    loss). Revenue is credit-normal, expenses are debit-normal; ``net_income``
    is revenue minus expenses.
  - ``balance_sheet`` — assets, liabilities and equity as of a date. Because the
    ledger is never "closed" into retained earnings here, the cumulative
    net income since inception is rolled into equity as a synthetic
    *Net income (current period)* line so the statement balances
    (``assets == liabilities + equity``).
  - ``cash_flow_statement`` (Phase 7) — the third core statement. Built with the
    *direct* method straight off the cash account(s): every journal entry that
    moves cash is decomposed into its non-cash contra lines, which are bucketed
    into operating / investing / financing activities by account type. By
    construction ``beginning_cash + net_change == ending_cash``, so the
    statement always reconciles to the cash balance on the balance sheet.

This is pure reporting on top of the Phase 2 GL — it introduces no new tables
and reuses the same posted entries as the trial balance, CAM, lifecycle, and AP
modules.
"""

from __future__ import annotations

import calendar
import uuid
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.general_ledger import (
    DEBIT_NORMAL_TYPES,
    JournalEntry,
    JournalEntryLine,
)

TWO = Decimal("0.01")
# Balancing tolerance: a balance sheet ties out when assets equal liabilities
# plus equity to within one cent, absorbing rounding in two-decimal currency math.
BALANCE_TOLERANCE = TWO

# Section ordering for the balance sheet and income statement.
_BALANCE_SHEET_SECTIONS = ("asset", "liability", "equity")
_INCOME_STATEMENT_SECTIONS = ("revenue", "expense")

# Cash-flow activity sections (Phase 7), in presentation order.
_CASH_FLOW_SECTIONS = ("operating", "investing", "financing")
# Non-cash contra accounts are mapped to a cash-flow activity by their GL
# account type. This is the conventional GAAP mapping: revenue/expense activity
# is operating, non-cash asset movements are investing, and liability/equity
# movements are financing.
_ACTIVITY_BY_ACCOUNT_TYPE = {
    "revenue": "operating",
    "expense": "operating",
    "asset": "investing",
    "liability": "financing",
    "equity": "financing",
}


def _q(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(TWO, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Period helpers
# ---------------------------------------------------------------------------

def period_bounds(
    year: int | None, month: int | None
) -> tuple[date | None, date | None]:
    """Translate ``year``/``month`` query params into an inclusive date range.

    - ``year`` and ``month`` → that single calendar month.
    - ``year`` only → that whole calendar year.
    - neither → an open range (since inception, no upper bound).
    """
    if year is None:
        return None, None
    if month is not None:
        if not (1 <= month <= 12):
            raise ValueError("Month must be between 1 and 12.")
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, 1), date(year, month, last_day)
    return date(year, 1, 1), date(year, 12, 31)


def as_of_date(year: int | None, month: int | None) -> date | None:
    """Translate ``year``/``month`` into a balance-sheet cutoff (inclusive end).

    - ``year`` and ``month`` → end of that month.
    - ``year`` only → end of that year.
    - neither → ``None`` (all activity to date).
    """
    if year is None:
        return None
    if month is not None:
        if not (1 <= month <= 12):
            raise ValueError("Month must be between 1 and 12.")
        return date(year, month, calendar.monthrange(year, month)[1])
    return date(year, 12, 31)


# ---------------------------------------------------------------------------
# Ledger aggregation
# ---------------------------------------------------------------------------

async def _account_sums(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    *,
    start: date | None = None,
    end: date | None = None,
) -> dict[uuid.UUID, dict]:
    """Per-account debit/credit totals over an inclusive ``[start, end]`` range.

    A ``None`` bound means unbounded on that side. Returns a map keyed by account
    id with ``code``, ``name``, ``type`` and summed ``debit``/``credit``.
    """
    stmt = (
        select(JournalEntry)
        .where(JournalEntry.organization_id == organization_id)
        .options(
            selectinload(JournalEntry.lines).selectinload(JournalEntryLine.account)
        )
    )
    if start is not None:
        stmt = stmt.where(JournalEntry.entry_date >= start)
    if end is not None:
        stmt = stmt.where(JournalEntry.entry_date <= end)

    entries = (await db.execute(stmt)).scalars().unique().all()

    totals: dict[uuid.UUID, dict] = {}
    for entry in entries:
        for line in entry.lines:
            acct = line.account
            row = totals.setdefault(
                acct.id,
                {
                    "account_id": acct.id,
                    "code": acct.code,
                    "name": acct.name,
                    "type": acct.type,
                    "debit": Decimal("0"),
                    "credit": Decimal("0"),
                },
            )
            row["debit"] += line.debit
            row["credit"] += line.credit
    return totals


def _natural_balance(row: dict) -> Decimal:
    """Account balance on its normal side (positive for a normal-side balance).

    For debit-normal accounts (assets, expenses) this is debit minus credit; for
    credit-normal accounts (liabilities, equity, revenue) it is credit minus
    debit (the negation of the net), so each balance reads positive when it sits
    on the account's natural side.
    """
    net = _q(row["debit"]) - _q(row["credit"])
    return net if row["type"] in DEBIT_NORMAL_TYPES else -net


def _section(totals: dict[uuid.UUID, dict], type_: str) -> tuple[list[dict], Decimal]:
    """Build the rows and total for one account type, dropping zero balances."""
    rows: list[dict] = []
    section_total = Decimal("0")
    for row in totals.values():
        if row["type"] != type_:
            continue
        amount = _natural_balance(row)
        if amount == 0:
            continue
        rows.append(
            {
                "account_id": row["account_id"],
                "code": row["code"],
                "name": row["name"],
                "amount": amount,
            }
        )
        section_total += amount
    rows.sort(key=lambda r: r["code"])
    return rows, _q(section_total)


# ---------------------------------------------------------------------------
# Income statement
# ---------------------------------------------------------------------------

async def income_statement(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    *,
    year: int | None = None,
    month: int | None = None,
) -> dict:
    """Revenue less expenses over the requested period."""
    start, end = period_bounds(year, month)
    totals = await _account_sums(db, organization_id, start=start, end=end)

    revenue_rows, total_revenue = _section(totals, "revenue")
    expense_rows, total_expenses = _section(totals, "expense")
    net_income = _q(total_revenue - total_expenses)

    return {
        "start_date": start,
        "end_date": end,
        "revenue": revenue_rows,
        "total_revenue": total_revenue,
        "expenses": expense_rows,
        "total_expenses": total_expenses,
        "net_income": net_income,
    }


# ---------------------------------------------------------------------------
# Balance sheet
# ---------------------------------------------------------------------------

async def balance_sheet(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    *,
    year: int | None = None,
    month: int | None = None,
) -> dict:
    """Assets, liabilities and equity as of the requested cutoff date.

    The cumulative net income since inception (revenue less expenses) is rolled
    into equity as a synthetic line so ``assets == liabilities + equity``.
    """
    end = as_of_date(year, month)
    totals = await _account_sums(db, organization_id, start=None, end=end)

    asset_rows, total_assets = _section(totals, "asset")
    liability_rows, total_liabilities = _section(totals, "liability")
    equity_rows, equity_accounts_total = _section(totals, "equity")

    # Temporary accounts (revenue/expense) have not been closed into retained
    # earnings, so fold their net into equity to make the statement balance.
    _, total_revenue = _section(totals, "revenue")
    _, total_expenses = _section(totals, "expense")
    net_income = _q(total_revenue - total_expenses)
    if net_income != 0:
        equity_rows.append(
            {
                "account_id": None,
                "code": "",
                "name": "Net income (current period)",
                "amount": net_income,
            }
        )
    total_equity = _q(equity_accounts_total + net_income)
    liabilities_and_equity = _q(total_liabilities + total_equity)
    balanced = abs(_q(total_assets) - liabilities_and_equity) < BALANCE_TOLERANCE

    return {
        "as_of_date": end,
        "assets": asset_rows,
        "total_assets": _q(total_assets),
        "liabilities": liability_rows,
        "total_liabilities": _q(total_liabilities),
        "equity": equity_rows,
        "total_equity": total_equity,
        "liabilities_and_equity": liabilities_and_equity,
        "net_income": net_income,
        "balanced": balanced,
    }


# ---------------------------------------------------------------------------
# Statement of cash flows (Phase 7)
# ---------------------------------------------------------------------------

def _is_cash_account(name: str, type_: str) -> bool:
    """Heuristic for a cash / cash-equivalent account.

    The default chart of accounts seeds a single ``Cash`` account, but an org may
    add others (e.g. "Petty Cash", "Cash - Operating"). Any asset account whose
    name contains the word "cash" is treated as cash for the cash-flow statement.
    """
    return type_ == "asset" and "cash" in (name or "").lower()


async def _cash_account_balance(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    *,
    end: date | None,
) -> Decimal:
    """Net cash balance (debit minus credit) across all cash accounts up to ``end``."""
    totals = await _account_sums(db, organization_id, start=None, end=end)
    balance = Decimal("0")
    for row in totals.values():
        if _is_cash_account(row["name"], row["type"]):
            balance += _q(row["debit"]) - _q(row["credit"])
    return _q(balance)


async def cash_flow_statement(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    *,
    year: int | None = None,
    month: int | None = None,
) -> dict:
    """Direct-method statement of cash flows over the requested period.

    Every journal entry that touches a cash account is decomposed into its
    non-cash contra lines. Each contra line's cash impact (``credit - debit`` —
    a credit to a contra account is a source of cash, a debit is a use) is
    bucketed into operating / investing / financing activities by the contra
    account's type. Entries that never touch cash (e.g. depreciation, or the
    initial right-of-use asset / lease-liability recognition) are excluded, so
    only real cash movements appear.

    Because each entry is balanced, the sum of the non-cash contra impacts equals
    the cash lines' net movement; the three activity sections therefore always
    sum to the period's change in cash, and
    ``beginning_cash + net_change == ending_cash`` ties back to the balance
    sheet's cash line.
    """
    start, end = period_bounds(year, month)

    stmt = (
        select(JournalEntry)
        .where(JournalEntry.organization_id == organization_id)
        .options(
            selectinload(JournalEntry.lines).selectinload(JournalEntryLine.account)
        )
    )
    if start is not None:
        stmt = stmt.where(JournalEntry.entry_date >= start)
    if end is not None:
        stmt = stmt.where(JournalEntry.entry_date <= end)
    entries = (await db.execute(stmt)).scalars().unique().all()

    # Accumulate each activity section as a map of account-id → line dict so
    # repeated postings to the same contra account collapse into one line.
    buckets: dict[str, dict[uuid.UUID, dict]] = {
        section: {} for section in _CASH_FLOW_SECTIONS
    }
    for entry in entries:
        touches_cash = any(
            _is_cash_account(line.account.name, line.account.type)
            for line in entry.lines
        )
        if not touches_cash:
            continue
        for line in entry.lines:
            acct = line.account
            if _is_cash_account(acct.name, acct.type):
                continue
            section = _ACTIVITY_BY_ACCOUNT_TYPE.get(acct.type)
            if section is None:
                continue
            impact = _q(line.credit) - _q(line.debit)
            row = buckets[section].setdefault(
                acct.id,
                {
                    "account_id": acct.id,
                    "code": acct.code,
                    "name": acct.name,
                    "amount": Decimal("0"),
                },
            )
            row["amount"] += impact

    sections: dict[str, dict] = {}
    net_change = Decimal("0")
    for section in _CASH_FLOW_SECTIONS:
        rows = [r for r in buckets[section].values() if _q(r["amount"]) != 0]
        for r in rows:
            r["amount"] = _q(r["amount"])
        rows.sort(key=lambda r: r["code"])
        section_total = _q(sum((r["amount"] for r in rows), Decimal("0")))
        sections[section] = {"lines": rows, "total": section_total}
        net_change += section_total
    net_change = _q(net_change)

    # Beginning cash is everything posted strictly before the period start; with
    # an open-ended (since-inception) period it is zero.
    if start is None:
        beginning_cash = Decimal("0.00")
    else:
        beginning_cash = await _cash_account_balance(
            db, organization_id, end=start - timedelta(days=1)
        )
    ending_cash = _q(beginning_cash + net_change)

    return {
        "start_date": start,
        "end_date": end,
        "operating": sections["operating"],
        "investing": sections["investing"],
        "financing": sections["financing"],
        "net_change_in_cash": net_change,
        "beginning_cash": beginning_cash,
        "ending_cash": ending_cash,
    }
