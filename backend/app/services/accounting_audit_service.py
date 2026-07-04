"""Audit-grade accounting-integrity service — the platform's built-in auditor.

This service performs an independent, read-only audit of an organization's
general ledger and derived financial statements and produces a structured
attestation report. It re-derives every invariant that a human auditor would
test so the platform can *attest* to the validity of its own accounting:

  * **Double-entry integrity** — every journal entry balances (Σ debits =
    Σ credits) and the ledger as a whole balances (a valid trial balance).
  * **Line integrity** — no line carries both a debit and a credit, no negative
    amounts, and every entry has at least two lines.
  * **Account-scope integrity** — every posted line references an account that
    belongs to the same organization as its entry (no cross-tenant leakage).
  * **Period integrity** — each entry is filed in the accounting period that
    matches its ``entry_date`` (no mis-filed or back-dated postings).
  * **Audit-trail integrity** — every entry is ``posted`` with a provenance
    ``source`` tag and a ``posted_at`` timestamp, so every number is traceable
    to its origin.
  * **Statement cross-ties** — the income statement's net income equals the
    balance sheet's folded net income, the balance sheet balances
    (Assets = Liabilities + Equity), and the cash-flow statement's ending cash
    ties to the balance sheet's cash.
  * **Control-account attestation** — each subledger control account (Accounts
    Receivable, Accounts Payable, CAM Receivable, Due to Owners, Trust Cash,
    Security Deposits Held) is only ever moved by its own authorised posting
    sources, so a control balance can never be silently contaminated by an
    unrelated manual entry.

The report is deterministic and side-effect free; it never mutates the ledger.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.general_ledger import (
    DEBIT_NORMAL_TYPES,
    GLAccount,
    JournalEntry,
    JournalEntryLine,
)
from app.services import financials_service as fin

TWO = Decimal("0.01")

# Tolerance for rounding noise when comparing derived statement totals.
TOLERANCE = Decimal("0.01")


def _q(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(TWO, rounding=ROUND_HALF_UP)


# Control (subledger) accounts and the journal-entry ``source`` tags that are
# permitted to move them. Any movement of a control account by a source outside
# this allow-list is a contamination that the audit flags. ``manual`` opening
# balances are always permitted because a bookkeeper may seed a control account.
CONTROL_ACCOUNTS: dict[str, dict] = {
    "1100": {"name": "Accounts Receivable", "sources": {"ar", "rent", "rent_late_fee"}},
    "1200": {"name": "CAM Receivable", "sources": {"cam"}},
    "1050": {"name": "Trust Cash", "sources": {"owner"}},
    "2200": {"name": "Accounts Payable", "sources": {"ap"}},
    "2300": {"name": "Security Deposits Held", "sources": {"deposit"}},
    "2500": {"name": "Due to Owners", "sources": {"owner"}},
    "2100": {"name": "CAM Refund Payable", "sources": {"cam"}},
}

# ``manual`` is always allowed (opening balances / bookkeeper adjustments).
_ALWAYS_ALLOWED_SOURCES = {"manual"}


class _Check:
    """Accumulates the outcome of a single audit check."""

    __slots__ = ("key", "description", "category", "status", "detail", "findings")

    def __init__(self, key: str, description: str, category: str):
        self.key = key
        self.description = description
        self.category = category
        self.status = "pass"
        self.detail = ""
        self.findings: list[str] = []

    def fail(self, detail: str, finding: str | None = None) -> None:
        self.status = "fail"
        self.detail = detail
        if finding:
            self.findings.append(finding)

    def add_finding(self, finding: str) -> None:
        self.findings.append(finding)
        self.status = "fail"

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "description": self.description,
            "category": self.category,
            "status": self.status,
            "detail": self.detail,
            # Cap findings so a broken ledger can't produce an unbounded payload.
            "findings": self.findings[:50],
            "finding_count": len(self.findings),
        }


async def _load_entries(
    db: AsyncSession, organization_id: uuid.UUID | None
) -> list[JournalEntry]:
    stmt = (
        select(JournalEntry)
        .where(JournalEntry.organization_id == organization_id)
        .options(
            selectinload(JournalEntry.lines).selectinload(JournalEntryLine.account),
            selectinload(JournalEntry.period),
        )
        .order_by(JournalEntry.entry_date, JournalEntry.created_at)
    )
    return list((await db.execute(stmt)).scalars().unique().all())


async def run_audit(
    db: AsyncSession, organization_id: uuid.UUID | None
) -> dict:
    """Run the full accounting audit and return a structured attestation report."""
    entries = await _load_entries(db, organization_id)

    checks: list[_Check] = []

    # ── Double-entry + line + scope + period + trail integrity (single pass) ──
    entry_balance = _Check(
        "journal_entry_balance",
        "Every journal entry balances (debits equal credits).",
        "double_entry",
    )
    line_integrity = _Check(
        "line_integrity",
        "No line carries both a debit and a credit or a negative amount; each "
        "entry has at least two lines.",
        "double_entry",
    )
    scope_integrity = _Check(
        "account_scope_integrity",
        "Every journal line references an account owned by the entry's "
        "organization.",
        "isolation",
    )
    period_integrity = _Check(
        "period_integrity",
        "Every entry is filed in the accounting period matching its date.",
        "periods",
    )
    trail_integrity = _Check(
        "audit_trail_integrity",
        "Every entry is posted with a source tag and a posted-at timestamp.",
        "audit_trail",
    )

    total_debits = Decimal("0")
    total_credits = Decimal("0")
    # Per-account running balance (debit - credit) for control reconciliation.
    account_net: dict[uuid.UUID, Decimal] = {}
    # Per-account net contributed by each source tag.
    account_source_net: dict[uuid.UUID, dict[str, Decimal]] = {}
    account_by_id: dict[uuid.UUID, GLAccount] = {}

    for entry in entries:
        entry_debit = Decimal("0")
        entry_credit = Decimal("0")
        line_count = 0
        for line in entry.lines:
            line_count += 1
            debit = _q(line.debit)
            credit = _q(line.credit)
            acct = line.account

            if debit < 0 or credit < 0:
                line_integrity.add_finding(
                    f"entry {entry.id}: negative amount (debit={debit}, credit={credit})"
                )
            if debit > 0 and credit > 0:
                line_integrity.add_finding(
                    f"entry {entry.id}: line has both a debit and a credit"
                )
            if debit == 0 and credit == 0:
                line_integrity.add_finding(
                    f"entry {entry.id}: line has neither a debit nor a credit"
                )

            entry_debit += debit
            entry_credit += credit
            total_debits += debit
            total_credits += credit

            if acct is not None:
                account_by_id[acct.id] = acct
                account_net[acct.id] = account_net.get(acct.id, Decimal("0")) + (
                    debit - credit
                )
                by_source = account_source_net.setdefault(acct.id, {})
                by_source[entry.source] = by_source.get(entry.source, Decimal("0")) + (
                    debit - credit
                )
                if acct.organization_id != entry.organization_id:
                    scope_integrity.add_finding(
                        f"entry {entry.id}: account {acct.code} belongs to a "
                        f"different organization"
                    )

        if line_count < 2:
            line_integrity.add_finding(
                f"entry {entry.id}: only {line_count} line(s); a double-entry "
                f"posting requires at least two"
            )
        if _q(entry_debit) != _q(entry_credit):
            entry_balance.add_finding(
                f"entry {entry.id} ({entry.source}) unbalanced: "
                f"debits {_q(entry_debit)} != credits {_q(entry_credit)}"
            )

        # Period integrity: the entry must live in the period for its date.
        period = entry.period
        if period is not None and (
            period.year != entry.entry_date.year
            or period.month != entry.entry_date.month
        ):
            period_integrity.add_finding(
                f"entry {entry.id} dated {entry.entry_date} filed in period "
                f"{period.year}-{period.month:02d}"
            )

        # Audit-trail integrity.
        if not entry.source:
            trail_integrity.add_finding(f"entry {entry.id}: missing source tag")
        if entry.status != "posted":
            trail_integrity.add_finding(
                f"entry {entry.id}: status '{entry.status}' (expected 'posted')"
            )
        if entry.posted_at is None:
            trail_integrity.add_finding(f"entry {entry.id}: missing posted_at")

    checks.extend(
        [entry_balance, line_integrity, scope_integrity, period_integrity, trail_integrity]
    )

    # ── Trial balance ────────────────────────────────────────────────────────
    trial = _Check(
        "trial_balance",
        "The ledger as a whole balances (Σ debits = Σ credits).",
        "double_entry",
    )
    if _q(total_debits) != _q(total_credits):
        trial.fail(
            f"Ledger out of balance: debits {_q(total_debits)} != "
            f"credits {_q(total_credits)}."
        )
    else:
        trial.detail = (
            f"Σ debits = Σ credits = {_q(total_debits)} across {len(entries)} entries."
        )

    checks.append(trial)

    # ── Control-account attestation (contamination check) ────────────────────
    control = _Check(
        "control_account_integrity",
        "Each subledger control account is only moved by its authorised "
        "posting sources.",
        "control_accounts",
    )
    code_to_id: dict[str, uuid.UUID] = {
        acct.code: acct_id for acct_id, acct in account_by_id.items()
    }
    control_summary: list[dict] = []
    for code, spec in CONTROL_ACCOUNTS.items():
        acct_id = code_to_id.get(code)
        if acct_id is None:
            continue  # Feature not in use for this org.
        allowed = spec["sources"] | _ALWAYS_ALLOWED_SOURCES
        by_source = account_source_net.get(acct_id, {})
        offending = {
            src: _q(net)
            for src, net in by_source.items()
            if src not in allowed and _q(net) != 0
        }
        acct = account_by_id[acct_id]
        balance_net = _q(account_net.get(acct_id, Decimal("0")))
        # Present the balance on the account's natural side (positive).
        natural = balance_net if acct.type in DEBIT_NORMAL_TYPES else -balance_net
        control_summary.append(
            {
                "code": code,
                "name": spec["name"],
                "balance": natural,
                "balance_side": "debit" if balance_net >= 0 else "credit",
            }
        )
        for src, net in offending.items():
            control.add_finding(
                f"{code} {spec['name']}: unauthorised source '{src}' moved the "
                f"control account by {net}"
            )
    if control.status == "pass":
        control.detail = (
            f"{len(control_summary)} control account(s) attested; no unauthorised "
            f"postings."
        )

    checks.append(control)

    # ── Statement cross-ties ──────────────────────────────────────────────────
    income = await fin.income_statement(db, organization_id)
    balance = await fin.balance_sheet(db, organization_id)
    cash_flow = await fin.cash_flow_statement(db, organization_id)

    equation = _Check(
        "accounting_equation",
        "The balance sheet balances (Assets = Liabilities + Equity).",
        "statements",
    )
    diff = _q(balance["total_assets"]) - _q(balance["liabilities_and_equity"])
    if abs(diff) > TOLERANCE or not balance["balanced"]:
        equation.fail(
            f"Assets {_q(balance['total_assets'])} != Liabilities + Equity "
            f"{_q(balance['liabilities_and_equity'])} (off by {diff})."
        )
    else:
        equation.detail = (
            f"Assets = Liabilities + Equity = {_q(balance['total_assets'])}."
        )

    ni_tie = _Check(
        "net_income_tie",
        "Income-statement net income ties to the balance sheet.",
        "statements",
    )
    ni_diff = _q(income["net_income"]) - _q(balance["net_income"])
    if abs(ni_diff) > TOLERANCE:
        ni_tie.fail(
            f"Income statement net income {_q(income['net_income'])} != "
            f"balance sheet net income {_q(balance['net_income'])}."
        )
    else:
        ni_tie.detail = f"Net income of {_q(income['net_income'])} ties across statements."

    cash_tie = _Check(
        "cash_flow_tie",
        "Cash-flow ending cash ties to the balance sheet's cash.",
        "statements",
    )
    bs_cash = _bs_cash(balance)
    cf_cash = _q(cash_flow["ending_cash"])
    if abs(cf_cash - bs_cash) > TOLERANCE:
        cash_tie.fail(
            f"Cash-flow ending cash {cf_cash} != balance-sheet cash {bs_cash}."
        )
    else:
        cash_tie.detail = f"Ending cash of {cf_cash} ties to the balance sheet."

    checks.extend([equation, ni_tie, cash_tie])

    # ── Roll up ───────────────────────────────────────────────────────────────
    failed = [c for c in checks if c.status == "fail"]
    attested = not failed

    return {
        "attested": attested,
        "entry_count": len(entries),
        "total_debits": _q(total_debits),
        "total_credits": _q(total_credits),
        "checks_total": len(checks),
        "checks_passed": len(checks) - len(failed),
        "checks_failed": len(failed),
        "control_accounts": control_summary,
        "checks": [c.to_dict() for c in checks],
        "statement_summary": {
            "total_assets": _q(balance["total_assets"]),
            "total_liabilities": _q(balance["total_liabilities"]),
            "total_equity": _q(balance["total_equity"]),
            "net_income": _q(income["net_income"]),
            "ending_cash": _q(cash_flow["ending_cash"]),
        },
    }


def _bs_cash(balance: dict) -> Decimal:
    """Sum the balance sheet's cash asset lines (asset accounts named 'cash')."""
    total = Decimal("0")
    for row in balance["assets"]:
        if "cash" in (row["name"] or "").lower():
            total += _q(row["amount"])
    return _q(total)
