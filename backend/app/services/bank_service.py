"""Bank-reconciliation service layer (Phase 1.2).

Keeps the ``/api/v1/bank`` router thin by holding the statement-import parsing and
the reconciliation rules:

  - parse an uploaded bank statement (CSV or OFX/QFX) into normalized transactions
  - import parsed transactions idempotently (de-duplicated on OFX ``FITID``)
  - the clearing workflow (cleared vs uncleared / outstanding items)
  - the reconciliation balance proof — starting balance + cleared activity must
    equal the statement ending balance before a reconciliation can be completed
  - a book (GL) balance for the mapped cash account as of a date, so the bank
    side can be proved against the audit-grade general ledger

All amounts are USD; multi-currency / FX is deferred. Live bank-feed aggregator
integration is intentionally out of scope for this phase — file import only.
"""

from __future__ import annotations

import csv
import io
import re
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.bank_account import BankAccount, BankReconciliation, BankTransaction
from app.models.general_ledger import JournalEntry, JournalEntryLine

TWO = Decimal("0.01")


class BankError(ValueError):
    """Raised for bank-reconciliation rule violations."""


def _q(value) -> Decimal:
    """Round to 2 decimal places (currency)."""
    try:
        return Decimal(str(value if value not in (None, "") else 0)).quantize(
            TWO, rounding=ROUND_HALF_UP
        )
    except (InvalidOperation, ValueError):
        raise BankError(f"Invalid amount: {value!r}")


# ---------------------------------------------------------------------------
# Statement parsing
# ---------------------------------------------------------------------------

# CSV header aliases (lower-cased) mapped to normalized fields.
_DATE_KEYS = {"date", "transaction date", "posted date", "post date"}
_DESC_KEYS = {"description", "memo", "name", "payee", "details"}
_AMOUNT_KEYS = {"amount", "value"}
_DEBIT_KEYS = {"debit", "withdrawal", "withdrawals", "money out", "paid out"}
_CREDIT_KEYS = {"credit", "deposit", "deposits", "money in", "paid in"}
_REF_KEYS = {"reference", "ref", "check number", "check", "cheque number"}

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%d/%m/%Y",
    "%Y%m%d",
    "%m-%d-%Y",
)


def _parse_date(raw: str) -> date:
    text = (raw or "").strip()
    if not text:
        raise BankError("Transaction is missing a date.")
    # OFX dates may include time/zone, e.g. 20260115120000[-5:EST]; keep digits.
    digits = re.match(r"^(\d{8})", text)
    if digits:
        try:
            return datetime.strptime(digits.group(1), "%Y%m%d").date()
        except ValueError:
            pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise BankError(f"Unrecognized date format: {raw!r}")


def _clean_amount(raw: str) -> Decimal:
    text = (raw or "").strip()
    if not text:
        return Decimal("0")
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]
    text = text.replace("$", "").replace(",", "").replace(" ", "")
    if text in ("", "-", "+"):
        return Decimal("0")
    value = _q(text)
    return -value if negative else value


def parse_statement(content: bytes | str, filename: str | None = None) -> tuple[list[dict], str]:
    """Parse an uploaded statement into normalized transaction dicts.

    Returns ``(transactions, source)`` where each transaction dict has
    ``txn_date``, ``description``, ``amount`` (signed), ``reference`` and ``fitid``
    keys, and ``source`` is one of ``"csv"`` / ``"ofx"``. The format is detected
    from the content (OFX/QFX markers) with the filename as a hint.
    """
    text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
    lowered = text.lstrip().lower()
    is_ofx = (
        "<ofx>" in lowered
        or "<stmttrn>" in lowered
        or "ofxheader" in lowered
        or (filename or "").lower().endswith((".ofx", ".qfx"))
    )
    if is_ofx:
        return _parse_ofx(text), "ofx"
    return _parse_csv(text), "csv"


def _parse_csv(text: str) -> list[dict]:
    # Sniff the delimiter but fall back to comma.
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise BankError("The CSV file has no header row.")

    field_map: dict[str, str] = {}
    for name in reader.fieldnames:
        key = (name or "").strip().lower()
        if key in _DATE_KEYS:
            field_map.setdefault("date", name)
        elif key in _AMOUNT_KEYS:
            field_map.setdefault("amount", name)
        elif key in _DEBIT_KEYS:
            field_map.setdefault("debit", name)
        elif key in _CREDIT_KEYS:
            field_map.setdefault("credit", name)
        elif key in _DESC_KEYS:
            field_map.setdefault("description", name)
        elif key in _REF_KEYS:
            field_map.setdefault("reference", name)

    if "date" not in field_map:
        raise BankError("The CSV must have a 'Date' column.")
    if "amount" not in field_map and not ("debit" in field_map or "credit" in field_map):
        raise BankError(
            "The CSV must have an 'Amount' column, or 'Debit'/'Credit' columns."
        )

    transactions: list[dict] = []
    for row in reader:
        if not any((v or "").strip() for v in row.values()):
            continue
        txn_date = _parse_date(row.get(field_map["date"], ""))
        if "amount" in field_map:
            amount = _clean_amount(row.get(field_map["amount"], ""))
        else:
            debit = _clean_amount(row.get(field_map.get("debit", ""), "")) if "debit" in field_map else Decimal("0")
            credit = _clean_amount(row.get(field_map.get("credit", ""), "")) if "credit" in field_map else Decimal("0")
            # Debits reduce the balance (withdrawals), credits increase it.
            amount = _q(abs(credit) - abs(debit))
        description = (row.get(field_map.get("description", ""), "") or "").strip() or None
        reference = (row.get(field_map.get("reference", ""), "") or "").strip() or None
        transactions.append(
            {
                "txn_date": txn_date,
                "description": description,
                "amount": amount,
                "reference": reference,
                "fitid": None,
            }
        )
    if not transactions:
        raise BankError("No transactions were found in the file.")
    return transactions


def _ofx_tag(block: str, tag: str) -> str | None:
    match = re.search(rf"<{tag}>([^<\r\n]*)", block, re.IGNORECASE)
    return match.group(1).strip() if match else None


def _parse_ofx(text: str) -> list[dict]:
    blocks = re.findall(r"<STMTTRN>(.*?)</STMTTRN>", text, re.IGNORECASE | re.DOTALL)
    if not blocks:
        raise BankError("No transactions (<STMTTRN>) were found in the OFX/QFX file.")
    transactions: list[dict] = []
    for block in blocks:
        raw_date = _ofx_tag(block, "DTPOSTED") or _ofx_tag(block, "DTUSER")
        if not raw_date:
            continue
        amount_raw = _ofx_tag(block, "TRNAMT")
        name = _ofx_tag(block, "NAME")
        memo = _ofx_tag(block, "MEMO")
        description = " ".join(p for p in (name, memo) if p) or None
        transactions.append(
            {
                "txn_date": _parse_date(raw_date),
                "description": description,
                "amount": _clean_amount(amount_raw or "0"),
                "reference": _ofx_tag(block, "CHECKNUM") or _ofx_tag(block, "REFNUM"),
                "fitid": _ofx_tag(block, "FITID"),
            }
        )
    if not transactions:
        raise BankError("No usable transactions were found in the OFX/QFX file.")
    return transactions


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

async def import_transactions(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    bank_account: BankAccount,
    transactions: list[dict],
    *,
    source: str = "csv",
    commit: bool = True,
) -> dict:
    """Persist parsed transactions for a bank account, skipping duplicates.

    De-duplication uses the OFX ``FITID`` when present (one per account); rows
    without a FITID are always inserted. Returns a summary with ``imported`` and
    ``skipped`` counts.
    """
    existing_fitids = set(
        (
            await db.execute(
                select(BankTransaction.fitid).where(
                    BankTransaction.bank_account_id == bank_account.id,
                    BankTransaction.fitid.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )

    imported = 0
    skipped = 0
    seen_batch: set[str] = set()
    for txn in transactions:
        fitid = txn.get("fitid")
        if fitid and (fitid in existing_fitids or fitid in seen_batch):
            skipped += 1
            continue
        if fitid:
            seen_batch.add(fitid)
        db.add(
            BankTransaction(
                organization_id=organization_id,
                bank_account_id=bank_account.id,
                txn_date=txn["txn_date"],
                description=txn.get("description"),
                amount=_q(txn["amount"]),
                reference=txn.get("reference"),
                fitid=fitid,
                import_source=source,
                status="unmatched",
            )
        )
        imported += 1

    if commit:
        await db.commit()
    else:
        await db.flush()
    return {"imported": imported, "skipped": skipped, "total": len(transactions)}


# ---------------------------------------------------------------------------
# Reconciliation math / balance proof
# ---------------------------------------------------------------------------

def cleared_total(recon: BankReconciliation) -> Decimal:
    """Signed sum of the transactions cleared into a reconciliation."""
    return _q(sum((_q(t.amount) for t in recon.transactions), Decimal("0")))


def cleared_deposits(recon: BankReconciliation) -> Decimal:
    return _q(sum((_q(t.amount) for t in recon.transactions if _q(t.amount) > 0), Decimal("0")))


def cleared_withdrawals(recon: BankReconciliation) -> Decimal:
    """Cleared withdrawals as a positive magnitude."""
    return _q(-sum((_q(t.amount) for t in recon.transactions if _q(t.amount) < 0), Decimal("0")))


def cleared_balance(recon: BankReconciliation) -> Decimal:
    """Beginning balance plus cleared activity — the reconciled bank balance."""
    return _q(_q(recon.beginning_balance) + cleared_total(recon))


def difference(recon: BankReconciliation) -> Decimal:
    """Ending balance less the cleared balance; zero means the statement ties out."""
    return _q(_q(recon.ending_balance) - cleared_balance(recon))


def is_balanced(recon: BankReconciliation) -> bool:
    return difference(recon) == Decimal("0.00")


def reconciliation_summary(recon: BankReconciliation) -> dict:
    """Structured balance proof for a reconciliation."""
    return {
        "beginning_balance": _q(recon.beginning_balance),
        "ending_balance": _q(recon.ending_balance),
        "cleared_deposits": cleared_deposits(recon),
        "cleared_withdrawals": cleared_withdrawals(recon),
        "cleared_balance": cleared_balance(recon),
        "difference": difference(recon),
        "is_balanced": is_balanced(recon),
        "cleared_count": len(recon.transactions),
    }


async def gl_book_balance(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    gl_account_id: uuid.UUID,
    *,
    as_of: date | None = None,
) -> Decimal:
    """Net (debit - credit) balance of the mapped GL cash account as of a date.

    This is the book side of the bank-reconciliation proof: an asset (cash)
    account's balance is debits less credits.
    """
    stmt = (
        select(
            func.coalesce(func.sum(JournalEntryLine.debit), 0)
            - func.coalesce(func.sum(JournalEntryLine.credit), 0)
        )
        .select_from(JournalEntryLine)
        .join(JournalEntry, JournalEntryLine.entry_id == JournalEntry.id)
        .where(
            JournalEntryLine.account_id == gl_account_id,
            JournalEntry.organization_id == organization_id,
        )
    )
    if as_of is not None:
        stmt = stmt.where(JournalEntry.entry_date <= as_of)
    result = await db.execute(stmt)
    return _q(result.scalar_one() or 0)


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------

async def get_reconciliation(
    db: AsyncSession, reconciliation_id: uuid.UUID, organization_id: uuid.UUID | None
) -> BankReconciliation | None:
    """Load a reconciliation with its cleared transactions eagerly for the org."""
    return (
        await db.execute(
            select(BankReconciliation)
            .where(
                BankReconciliation.id == reconciliation_id,
                BankReconciliation.organization_id == organization_id,
            )
            .options(selectinload(BankReconciliation.transactions))
        )
    ).scalar_one_or_none()


async def suggested_beginning_balance(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    bank_account_id: uuid.UUID,
) -> Decimal:
    """Ending balance of the most recent completed reconciliation, else zero."""
    prior = (
        await db.execute(
            select(BankReconciliation.ending_balance)
            .where(
                BankReconciliation.organization_id == organization_id,
                BankReconciliation.bank_account_id == bank_account_id,
                BankReconciliation.status == "completed",
            )
            .order_by(BankReconciliation.statement_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return _q(prior or 0)
