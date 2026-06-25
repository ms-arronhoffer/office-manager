"""General-ledger service layer (Phase 2).

Encapsulates the double-entry rules so routers stay thin:
  - default chart-of-accounts seeding
  - get-or-create accounting periods
  - balanced-entry validation and posting (blocked for closed periods)
  - period close / reopen
  - trial balance
  - posting a lease's ASC 842 / IFRS 16 entries into the GL
  - QuickBooks-compatible general-journal CSV export
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.general_ledger import (
    ACCOUNT_TYPES,
    AccountingPeriod,
    GLAccount,
    JournalEntry,
    JournalEntryLine,
)

TWO = Decimal("0.01")


def _q(value) -> Decimal:
    return Decimal(str(value)).quantize(TWO, rounding=ROUND_HALF_UP)


class GLError(ValueError):
    """Raised for general-ledger rule violations (unbalanced, closed period, ...)."""


# Default chart of accounts seeded for an organization on first use. Codes follow
# a conventional numbering scheme (1xxx asset, 2xxx liability, 3xxx equity,
# 4xxx revenue, 6xxx expense). Account names align with the lease-accounting
# journal entry account labels so lease postings map cleanly.
DEFAULT_ACCOUNTS: list[tuple[str, str, str]] = [
    ("1000", "Cash", "asset"),
    ("1500", "Right-of-Use Asset", "asset"),
    ("1510", "Accumulated Depreciation", "asset"),
    ("2000", "Lease Liability", "liability"),
    ("3000", "Retained Earnings", "equity"),
    ("4000", "Rental Income", "revenue"),
    ("6000", "Operating Lease Cost", "expense"),
    ("6100", "Interest Expense", "expense"),
    ("6200", "Depreciation Expense", "expense"),
]


# ---------------------------------------------------------------------------
# Chart of accounts
# ---------------------------------------------------------------------------

async def seed_default_accounts(
    db: AsyncSession, organization_id: uuid.UUID | None
) -> list[GLAccount]:
    """Create the default chart of accounts for an org if it has none yet."""
    existing = (
        await db.execute(
            select(GLAccount).where(GLAccount.organization_id == organization_id)
        )
    ).scalars().all()
    if existing:
        return existing

    created: list[GLAccount] = []
    for code, name, type_ in DEFAULT_ACCOUNTS:
        acct = GLAccount(
            organization_id=organization_id, code=code, name=name, type=type_
        )
        db.add(acct)
        created.append(acct)
    await db.commit()
    for acct in created:
        await db.refresh(acct)
    return created


async def get_account_map(
    db: AsyncSession, organization_id: uuid.UUID | None
) -> dict[str, GLAccount]:
    """Return a {account_name: GLAccount} map for an org's active accounts."""
    accounts = (
        await db.execute(
            select(GLAccount).where(GLAccount.organization_id == organization_id)
        )
    ).scalars().all()
    return {a.name: a for a in accounts}


def validate_account_type(type_: str) -> None:
    if type_ not in ACCOUNT_TYPES:
        raise GLError(
            f"Invalid account type '{type_}'. Must be one of: {', '.join(sorted(ACCOUNT_TYPES))}."
        )


# ---------------------------------------------------------------------------
# Periods
# ---------------------------------------------------------------------------

async def get_or_create_period(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    year: int,
    month: int,
    *,
    commit: bool = True,
) -> AccountingPeriod:
    """Return the period for (year, month), creating an open one if absent."""
    if not (1 <= month <= 12):
        raise GLError("Month must be between 1 and 12.")
    period = (
        await db.execute(
            select(AccountingPeriod).where(
                AccountingPeriod.organization_id == organization_id,
                AccountingPeriod.year == year,
                AccountingPeriod.month == month,
            )
        )
    ).scalar_one_or_none()
    if period is None:
        period = AccountingPeriod(
            organization_id=organization_id, year=year, month=month, status="open"
        )
        db.add(period)
        if commit:
            await db.commit()
            await db.refresh(period)
        else:
            await db.flush()
    return period


async def close_period(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    year: int,
    month: int,
    closed_by_id: uuid.UUID | None,
) -> AccountingPeriod:
    """Close a period, locking it against further postings."""
    period = await get_or_create_period(db, organization_id, year, month)
    if period.status == "closed":
        raise GLError(f"Period {year}-{month:02d} is already closed.")
    period.status = "closed"
    period.closed_at = datetime.now(timezone.utc)
    period.closed_by_id = closed_by_id
    await db.commit()
    await db.refresh(period)
    return period


async def reopen_period(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    year: int,
    month: int,
) -> AccountingPeriod:
    """Reopen a previously closed period."""
    period = await get_or_create_period(db, organization_id, year, month)
    if period.status != "closed":
        raise GLError(f"Period {year}-{month:02d} is not closed.")
    period.status = "open"
    period.closed_at = None
    period.closed_by_id = None
    await db.commit()
    await db.refresh(period)
    return period


# ---------------------------------------------------------------------------
# Journal entries
# ---------------------------------------------------------------------------

def _validate_balanced(lines: list[dict]) -> tuple[Decimal, Decimal]:
    """Ensure lines are non-empty, non-negative, and debits == credits."""
    if not lines:
        raise GLError("A journal entry must have at least one line.")
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    for line in lines:
        debit = _q(line.get("debit") or 0)
        credit = _q(line.get("credit") or 0)
        if debit < 0 or credit < 0:
            raise GLError("Debit and credit amounts must be non-negative.")
        if debit > 0 and credit > 0:
            raise GLError("A line cannot have both a debit and a credit amount.")
        if debit == 0 and credit == 0:
            raise GLError("Each line must have a non-zero debit or credit.")
        total_debit += debit
        total_credit += credit
    total_debit = _q(total_debit)
    total_credit = _q(total_credit)
    if total_debit != total_credit:
        raise GLError(
            f"Journal entry is unbalanced: debits {total_debit} != credits {total_credit}."
        )
    return total_debit, total_credit


async def create_journal_entry(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    *,
    entry_date: date,
    lines: list[dict],
    memo: str | None = None,
    source: str = "manual",
    source_ref: str | None = None,
    posted_by_id: uuid.UUID | None = None,
    commit: bool = True,
) -> JournalEntry:
    """Validate and persist a balanced journal entry, posting into its period.

    Each line dict must contain ``account_id`` and one of ``debit``/``credit``.
    Raises GLError if unbalanced, if an account is invalid, or if the target
    period is closed.
    """
    _validate_balanced(lines)

    # Resolve and validate accounts belong to the org.
    account_ids = {uuid.UUID(str(line["account_id"])) for line in lines}
    accounts = (
        await db.execute(
            select(GLAccount).where(
                GLAccount.id.in_(account_ids),
                GLAccount.organization_id == organization_id,
            )
        )
    ).scalars().all()
    found = {a.id for a in accounts}
    missing = account_ids - found
    if missing:
        raise GLError(f"Unknown account id(s): {', '.join(str(m) for m in missing)}.")

    period = await get_or_create_period(
        db, organization_id, entry_date.year, entry_date.month, commit=False
    )
    if period.status == "closed":
        raise GLError(
            f"Cannot post to closed period {period.year}-{period.month:02d}."
        )

    entry = JournalEntry(
        organization_id=organization_id,
        period=period,
        entry_date=entry_date,
        memo=memo,
        source=source,
        source_ref=source_ref,
        status="posted",
        posted_at=datetime.now(timezone.utc),
        posted_by_id=posted_by_id,
    )
    for idx, line in enumerate(lines, start=1):
        entry.lines.append(
            JournalEntryLine(
                account_id=uuid.UUID(str(line["account_id"])),
                line_number=idx,
                debit=_q(line.get("debit") or 0),
                credit=_q(line.get("credit") or 0),
                memo=line.get("memo"),
            )
        )
    db.add(entry)
    if commit:
        await db.commit()
        await db.refresh(entry)
    else:
        await db.flush()
    return entry


# ---------------------------------------------------------------------------
# Lease -> GL posting
# ---------------------------------------------------------------------------

async def post_lease_entries(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    lease,
    *,
    posted_by_id: uuid.UUID | None = None,
) -> list[JournalEntry]:
    """Generate and post GL journal entries from a lease's ASC 842 / IFRS 16 schedule.

    Re-posting a lease first removes any prior ``lease``-sourced entries for that
    lease so the GL is not double-counted. Entries that fall in a closed period
    are skipped (the open periods are still posted).
    """
    from app.services.lease_accounting import compute_lease_accounting

    data = compute_lease_accounting(lease, include_journal_entries=True)
    if data.get("exempt"):
        raise GLError(
            data.get("exempt_reason", "Lease is exempt from GL recognition.")
        )

    await seed_default_accounts(db, organization_id)
    account_map = await get_account_map(db, organization_id)

    # Remove any existing lease-sourced entries for this lease (idempotent re-post).
    existing = (
        await db.execute(
            select(JournalEntry).where(
                JournalEntry.organization_id == organization_id,
                JournalEntry.source == "lease",
                JournalEntry.source_ref == str(lease.id),
            )
        )
    ).scalars().all()
    for e in existing:
        await db.delete(e)

    # Group the flat journal_entries list (one dict per debit/credit leg) by date.
    by_date: dict[date, list[dict]] = {}
    for je in data["journal_entries"]:
        account_name = je["account"]
        if account_name not in account_map:
            # Skip informational placeholder rows that aren't real accounts.
            continue
        by_date.setdefault(je["date"], []).append(je)

    created: list[JournalEntry] = []
    for entry_date in sorted(by_date.keys()):
        legs = by_date[entry_date]
        lines = []
        for leg in legs:
            acct = account_map[leg["account"]]
            lines.append(
                {
                    "account_id": acct.id,
                    "debit": leg["debit"] or 0,
                    "credit": leg["credit"] or 0,
                    "memo": None,
                }
            )
        try:
            _validate_balanced(lines)
        except GLError:
            # Skip any date whose legs don't net to zero (defensive).
            continue

        period = await get_or_create_period(
            db, organization_id, entry_date.year, entry_date.month, commit=False
        )
        if period.status == "closed":
            continue

        entry = await create_journal_entry(
            db,
            organization_id,
            entry_date=entry_date,
            lines=lines,
            memo=f"Lease: {lease.lease_name}",
            source="lease",
            source_ref=str(lease.id),
            posted_by_id=posted_by_id,
            commit=False,
        )
        created.append(entry)

    await db.commit()
    # Session uses expire_on_commit=False, so in-memory line collections remain
    # accessible; avoid refresh() here which would expire the loaded lines.
    return created


# ---------------------------------------------------------------------------
# Trial balance
# ---------------------------------------------------------------------------

async def trial_balance(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    *,
    year: int | None = None,
    month: int | None = None,
) -> list[dict]:
    """Return per-account debit/credit totals, optionally filtered to a period.

    Filtering is inclusive up to the end of (year, month) when both are given,
    or to the whole ``year`` when only year is given.
    """
    stmt = (
        select(JournalEntry)
        .where(JournalEntry.organization_id == organization_id)
        .options(selectinload(JournalEntry.lines).selectinload(JournalEntryLine.account))
    )
    if year is not None and month is not None:
        cutoff = date(year, month, 28)
        stmt = stmt.where(JournalEntry.entry_date <= cutoff)
    elif year is not None:
        stmt = stmt.where(JournalEntry.entry_date <= date(year, 12, 31))

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

    rows = []
    for row in totals.values():
        debit = _q(row["debit"])
        credit = _q(row["credit"])
        net = debit - credit
        rows.append(
            {
                **row,
                "debit": debit,
                "credit": credit,
                # Balance shown on the account's normal side (positive).
                "balance": net if net >= 0 else -net,
                "balance_side": "debit" if net >= 0 else "credit",
            }
        )
    rows.sort(key=lambda r: r["code"])
    return rows


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

async def export_journal_csv(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    *,
    year: int | None = None,
    month: int | None = None,
) -> str:
    """Export posted journal entries as a QuickBooks-importable general-journal CSV.

    The column layout (Date, Journal No., Account, Debit, Credit, Memo) matches
    the QuickBooks Online general-journal import template, with one row per line.
    """
    stmt = (
        select(JournalEntry)
        .where(JournalEntry.organization_id == organization_id)
        .options(selectinload(JournalEntry.lines).selectinload(JournalEntryLine.account))
        .order_by(JournalEntry.entry_date, JournalEntry.created_at)
    )
    if year is not None and month is not None:
        stmt = stmt.where(
            JournalEntry.entry_date >= date(year, month, 1),
            JournalEntry.entry_date <= date(year, month, 28),
        )
    elif year is not None:
        stmt = stmt.where(
            JournalEntry.entry_date >= date(year, 1, 1),
            JournalEntry.entry_date <= date(year, 12, 31),
        )

    entries = (await db.execute(stmt)).scalars().unique().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Date", "Journal No.", "Account", "Debit", "Credit", "Memo"])
    for idx, entry in enumerate(entries, start=1):
        journal_no = f"JE-{idx:05d}"
        for line in entry.lines:
            writer.writerow(
                [
                    entry.entry_date.isoformat(),
                    journal_no,
                    f"{line.account.code} {line.account.name}",
                    f"{float(line.debit):.2f}" if line.debit else "",
                    f"{float(line.credit):.2f}" if line.credit else "",
                    line.memo or entry.memo or "",
                ]
            )
    return buf.getvalue()
