"""CAM schedule history: normalization, import and period-aware resolution.

An organization onboarding an existing tenancy typically has years of prior
lease documents, amendments and reconciliation statements. Those prior years
are imported into ``lease_cam_entries`` as ``period_status='historical'`` rows
so the portfolio carries its full financial history, while the **active lease
record remains the single source of truth for the current numbers**.

The invariant this module exists to protect: importing history never mutates
any ``Lease`` financial column. Promotion of a row's numbers onto the lease is a
separate, deliberate action (see ``promote_entry_to_lease``).

Responsibilities:

* :func:`normalize_history_rows` — coerce loosely-shaped AI/CSV rows (aliases,
  currency strings, percent signs, month names) into the canonical row shape.
* :func:`parse_history_csv` — the same canonical rows from a spreadsheet export.
* :func:`import_history_rows` — dedupe, detect conflicts with the active lease
  term, and persist a batch under one ``import_batch_id``.
* :func:`resolve_schedule` — resolve each row's effective CAM charge, chaining
  ``percent_increase`` rows **within their own period group** so historical
  years can never re-base the active schedule.
"""

from __future__ import annotations

import csv
import io
import re
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lease import (
    CAM_PERIOD_STATUSES,
    CAM_RENT_FREQUENCIES,
    Lease,
    LeaseCamEntry,
)

# Canonical keys of a proposed history row, and the looser aliases a model or a
# spreadsheet may use for them. Aliases are matched after normalising to
# lower-case snake case.
_ROW_ALIASES: dict[str, tuple[str, ...]] = {
    "year": ("year", "lease_year", "period", "calendar_year"),
    "period_start": ("period_start", "start", "start_date", "from", "period_from"),
    "period_end": ("period_end", "end", "end_date", "to", "period_to"),
    "base_rent_amount": (
        "base_rent_amount", "base_rent", "rent", "rent_amount", "annual_base_rent",
        "monthly_base_rent",
    ),
    "base_rent_frequency": (
        "base_rent_frequency", "rent_frequency", "frequency", "payment_frequency",
    ),
    "base_rent_escalation_rate": (
        "base_rent_escalation_rate", "escalation_percent", "escalation",
        "escalation_rate", "rent_escalation", "annual_escalation_rate",
    ),
    "amount": ("amount", "cam_amount", "cam", "cam_charge", "cam_total"),
    "percent_increase": (
        "percent_increase", "cam_percent_increase", "cam_increase",
        "cam_escalation_percent",
    ),
    "cam_psf": ("cam_psf", "cam_per_sqft", "cam_per_square_foot", "psf"),
    "operating_expense_amount": (
        "operating_expense_amount", "operating_expenses", "opex", "opex_amount",
    ),
    "reconciliation_true_up": (
        "reconciliation_true_up", "true_up", "trueup", "reconciliation",
        "reconciliation_amount", "settlement",
    ),
    "notes": ("notes", "note", "comment", "comments", "description"),
    "extraction_confidence": ("extraction_confidence", "confidence"),
    "period_status": ("period_status", "status"),
}

# Money-ish and rate-ish keys, used to pick the right coercion.
_MONEY_KEYS = (
    "base_rent_amount", "amount", "operating_expense_amount",
    "reconciliation_true_up", "cam_psf",
)
_RATE_KEYS = ("base_rent_escalation_rate", "percent_increase")

_MONTHLY_HINTS = ("month", "mo", "/mo", "per month")
_QUARTERLY_HINTS = ("quarter", "qtr", "/qtr", "per quarter")
_ANNUAL_HINTS = ("annual", "year", "yr", "/yr", "per year", "annually")

MAX_HISTORY_ROWS = 200


class CamImportError(ValueError):
    """Raised when a history import request cannot be honoured."""


def _snake(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip("_")


def _canonical_key(key: str) -> str | None:
    snake = _snake(key)
    for canonical, aliases in _ROW_ALIASES.items():
        if snake == canonical or snake in aliases:
            return canonical
    return None


def _to_decimal(value: Any) -> Decimal | None:
    """Parse a money/rate value that may arrive as ``"$12,500.50"`` or ``"3%"``."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    text = str(value).strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    cleaned = re.sub(r"[^0-9.\-]", "", text)
    if cleaned in ("", "-", ".", "-."):
        return None
    try:
        parsed = Decimal(cleaned)
    except InvalidOperation:
        return None
    return -parsed if negative and parsed > 0 else parsed


def _to_rate(value: Any) -> Decimal | None:
    """Coerce a percentage to a decimal fraction (``3`` / ``"3%"`` -> ``0.03``)."""
    parsed = _to_decimal(value)
    if parsed is None:
        return None
    had_percent_sign = isinstance(value, str) and "%" in value
    # Models are asked for fractions, but "3" and "3%" both mean 3 %.
    if had_percent_sign or abs(parsed) > 1:
        parsed = parsed / Decimal("100")
    return parsed


def _to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _to_year(value: Any, fallback: date | None = None) -> int | None:
    parsed = _to_decimal(value)
    if parsed is not None:
        year = int(parsed)
        if 1900 <= year <= 2200:
            return year
    # "2019-2020" or "FY2019"
    match = re.search(r"(19|20)\d{2}", str(value or ""))
    if match:
        return int(match.group(0))
    if fallback is not None:
        return fallback.year
    return None


def _to_frequency(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text in CAM_RENT_FREQUENCIES:
        return text
    if any(hint in text for hint in _MONTHLY_HINTS):
        return "monthly"
    if any(hint in text for hint in _QUARTERLY_HINTS):
        return "quarterly"
    if any(hint in text for hint in _ANNUAL_HINTS):
        return "annually"
    return None


def _to_confidence(value: Any) -> Decimal | None:
    parsed = _to_decimal(value)
    if parsed is None:
        return None
    if parsed > 1:
        parsed = parsed / Decimal("100")
    if parsed < 0 or parsed > 1:
        return None
    return parsed.quantize(Decimal("0.001"))


def normalize_history_rows(raw_rows: Any) -> list[dict[str, Any]]:
    """Coerce loosely-shaped extracted rows into canonical, deduped rows.

    Accepts the list a model or CSV parser produced, tolerating alias keys,
    currency/percent formatting and out-of-order rows. Rows without a usable
    year are dropped; duplicate years are merged (the first non-empty value for
    each field wins, matching the segment-merge rule used for AI extraction).
    Returns rows sorted by year.
    """
    if not isinstance(raw_rows, list):
        return []
    merged: dict[tuple[int, str | None], dict[str, Any]] = {}
    for raw in raw_rows[: MAX_HISTORY_ROWS * 4]:
        if not isinstance(raw, dict):
            continue
        mapped: dict[str, Any] = {}
        for key, value in raw.items():
            canonical = _canonical_key(key)
            if canonical and canonical not in mapped:
                mapped[canonical] = value

        period_start = _to_date(mapped.get("period_start"))
        period_end = _to_date(mapped.get("period_end"))
        year = _to_year(mapped.get("year"), fallback=period_start or period_end)
        if year is None:
            continue

        row: dict[str, Any] = {
            "year": year,
            "period_start": period_start,
            "period_end": period_end,
            "base_rent_frequency": _to_frequency(mapped.get("base_rent_frequency")),
            "notes": (str(mapped["notes"]).strip()[:1000] if mapped.get("notes") else None),
            "extraction_confidence": _to_confidence(mapped.get("extraction_confidence")),
        }
        for key in _MONEY_KEYS:
            row[key] = _to_decimal(mapped.get(key))
        for key in _RATE_KEYS:
            row[key] = _to_rate(mapped.get(key))

        status = str(mapped.get("period_status") or "").strip().lower()
        row["period_status"] = status if status in CAM_PERIOD_STATUSES else None
        # A row quoting only a percentage increase is a percent-increase row.
        row["charge_type"] = (
            "percent_increase"
            if row.get("amount") is None and row.get("percent_increase") is not None
            else "fixed"
        )

        key = (year, row["period_status"])
        existing = merged.get(key)
        if existing is None:
            merged[key] = row
            continue
        for field, value in row.items():
            if existing.get(field) in (None, "") and value not in (None, ""):
                existing[field] = value

    rows = sorted(merged.values(), key=lambda r: r["year"])
    return rows[:MAX_HISTORY_ROWS]


def parse_history_csv(content: bytes | str) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse a spreadsheet export of per-year financials into canonical rows.

    Column headers are matched against the same alias table the AI extractor
    uses, so ``Year, Base Rent, CAM, Escalation %`` and
    ``year,base_rent_amount,amount,base_rent_escalation_rate`` both work.
    Returns ``(rows, warnings)``; the rows still require explicit import.
    """
    if isinstance(content, bytes):
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("latin-1", errors="replace")
    else:
        text = content
    text = text.strip()
    if not text:
        raise CamImportError("The uploaded file is empty.")

    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise CamImportError("The uploaded file has no header row.")

    unknown = [
        name for name in reader.fieldnames
        if name and _canonical_key(name) is None
    ]
    raw_rows = [row for row in reader]
    rows = normalize_history_rows(raw_rows)
    warnings: list[str] = []
    if unknown:
        warnings.append(
            "Ignored unrecognised column(s): " + ", ".join(sorted(set(unknown))[:10])
        )
    if not rows:
        raise CamImportError(
            "No rows with a usable year were found. Include a 'year' column."
        )
    if len(raw_rows) > len(rows):
        warnings.append(
            f"{len(raw_rows) - len(rows)} row(s) were skipped or merged by year."
        )
    return rows, warnings


def coerce_date(value: Any) -> date | None:
    """Public wrapper over the tolerant date coercion used for extracted values."""
    return _to_date(value)


def derive_period_status(row_year: int, *, today: date | None = None) -> str:
    """Classify a lease-year relative to today (used by ``period_status='auto'``)."""
    current_year = (today or datetime.now(timezone.utc).date()).year
    if row_year < current_year:
        return "historical"
    if row_year > current_year:
        return "projected"
    return "current"


def _row_period(row: dict[str, Any]) -> tuple[date, date]:
    """The row's covered period, defaulting to its calendar year."""
    year = int(row["year"])
    start = row.get("period_start") or date(year, 1, 1)
    end = row.get("period_end") or date(year, 12, 31)
    if end < start:
        start, end = end, start
    return start, end


def overlaps_active_term(row: dict[str, Any], lease: Lease) -> bool:
    """Whether a row's period overlaps the active lease's own term.

    A historical row that covers time the active lease is billing is almost
    always a mis-scoped document (e.g. the current lease re-imported as
    history), so the import reports it as a conflict for explicit review.
    """
    start = lease.lease_commencement_date
    end = lease.lease_expiration
    if start is None and end is None:
        return False
    row_start, row_end = _row_period(row)
    if start is not None and row_end < start:
        return False
    if end is not None and row_start > end:
        return False
    return True


def _assign_row_fields(entry: LeaseCamEntry, row: dict[str, Any]) -> None:
    """Copy the canonical financial fields of ``row`` onto ``entry``."""
    entry.charge_type = row.get("charge_type") or "fixed"
    entry.amount = row.get("amount")
    entry.percent_increase = row.get("percent_increase")
    entry.period_start = row.get("period_start")
    entry.period_end = row.get("period_end")
    entry.base_rent_amount = row.get("base_rent_amount")
    entry.base_rent_frequency = row.get("base_rent_frequency")
    entry.base_rent_escalation_rate = row.get("base_rent_escalation_rate")
    entry.operating_expense_amount = row.get("operating_expense_amount")
    entry.cam_psf = row.get("cam_psf")
    entry.reconciliation_true_up = row.get("reconciliation_true_up")
    entry.extraction_confidence = row.get("extraction_confidence")
    if row.get("gl_account_id") is not None:
        entry.gl_account_id = row["gl_account_id"]
    if row.get("notes") is not None:
        entry.notes = row["notes"]


async def import_history_rows(
    db: AsyncSession,
    *,
    lease: Lease,
    rows: Sequence[dict[str, Any]],
    mode: str = "skip_existing",
    period_status: str = "historical",
    source: str = "ai_import",
    source_document_id: uuid.UUID | None = None,
    allow_active_period_overlap: bool = False,
    organization_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Persist reviewed history rows onto ``lease``'s CAM schedule.

    Rows are deduplicated on ``(lease_id, year, period_status)`` — long-lived
    databases can already hold several rows for one lease-year, so uniqueness is
    enforced here rather than by a database constraint. ``mode`` decides what
    happens when a row for that key already exists: ``skip_existing`` keeps it,
    ``overwrite`` replaces its values, ``append`` adds another row alongside.

    Every row written in one call shares an ``import_batch_id`` so a bad import
    can be reverted wholesale. **No ``Lease`` column is written by this
    function** — see :func:`promote_entry_to_lease`.
    """
    if not rows:
        raise CamImportError("No rows to import.")
    if len(rows) > MAX_HISTORY_ROWS:
        raise CamImportError(
            f"Too many rows in one import (max {MAX_HISTORY_ROWS})."
        )

    batch_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    existing_rows = (
        await db.execute(
            select(LeaseCamEntry).where(LeaseCamEntry.lease_id == lease.id)
        )
    ).scalars().all()
    by_key: dict[tuple[int, str], LeaseCamEntry] = {}
    for entry in existing_rows:
        by_key.setdefault((entry.year, entry.period_status or "current"), entry)

    results: list[dict[str, Any]] = []
    counts = {"created": 0, "updated": 0, "skipped": 0, "conflicts": 0}

    for row in rows:
        year = int(row["year"])
        status = row.get("period_status") or period_status
        if status == "auto":
            status = derive_period_status(year)
        if status not in CAM_PERIOD_STATUSES:
            status = "historical"

        if (
            status == "historical"
            and not allow_active_period_overlap
            and overlaps_active_term(row, lease)
        ):
            counts["conflicts"] += 1
            results.append(
                {
                    "year": year,
                    "status": "conflict",
                    "entry_id": None,
                    "reason": (
                        "Period overlaps the active lease term; the active lease "
                        "remains the source of truth for these numbers."
                    ),
                }
            )
            continue

        key = (year, status)
        existing = by_key.get(key)
        if existing is not None and mode == "skip_existing":
            counts["skipped"] += 1
            results.append(
                {
                    "year": year,
                    "status": "skipped",
                    "entry_id": existing.id,
                    "reason": f"A {status} row already exists for {year}.",
                }
            )
            continue

        if existing is not None and mode == "overwrite":
            _assign_row_fields(existing, row)
            existing.period_status = status
            existing.source = source
            existing.source_document_id = source_document_id
            existing.import_batch_id = batch_id
            existing.review_status = "accepted"
            existing.imported_at = now
            existing.updated_at = now
            counts["updated"] += 1
            results.append(
                {"year": year, "status": "updated", "entry_id": existing.id, "reason": None}
            )
            continue

        entry = LeaseCamEntry(
            lease_id=lease.id,
            organization_id=organization_id,
            year=year,
            period_status=status,
            source=source,
            source_document_id=source_document_id,
            import_batch_id=batch_id,
            review_status="accepted",
            imported_at=now,
        )
        _assign_row_fields(entry, row)
        db.add(entry)
        await db.flush()
        by_key.setdefault(key, entry)
        counts["created"] += 1
        results.append(
            {"year": year, "status": "created", "entry_id": entry.id, "reason": None}
        )

    return {"import_batch_id": batch_id, "results": results, **counts}


def promote_entry_to_lease(entry: LeaseCamEntry, lease: Lease) -> list[str]:
    """Copy a schedule row's numbers onto the lease's live financial terms.

    This is the **only** path that mutates the active lease's financials from a
    CAM schedule row, and it is always an explicit user action. Returns the list
    of lease fields that were changed; empty when the row carries no promotable
    figures.
    """
    changed: list[str] = []
    if entry.base_rent_amount is not None:
        lease.payment_amount = entry.base_rent_amount
        changed.append("payment_amount")
        if entry.base_rent_frequency:
            lease.payment_frequency = entry.base_rent_frequency
            changed.append("payment_frequency")
    if entry.base_rent_escalation_rate is not None:
        lease.annual_escalation_rate = entry.base_rent_escalation_rate
        changed.append("annual_escalation_rate")
    return changed


def resolve_schedule(entries: Iterable[LeaseCamEntry]) -> dict[uuid.UUID, Decimal | None]:
    """Resolve each row's effective CAM charge for its year.

    A ``fixed`` row is its own amount. A ``percent_increase`` row grows the
    prior year's resolved charge **within the same period group**: historical
    rows chain among themselves and never re-base the current/projected
    schedule, so importing eight years of history cannot silently change what
    the active lease is billing today.

    Rows whose chain has no fixed starting point resolve to ``None``.
    """
    resolved: dict[uuid.UUID, Decimal | None] = {}
    grouped: dict[str, list[LeaseCamEntry]] = {}
    for entry in entries:
        # Current and projected rows form one continuous active schedule.
        status = entry.period_status or "current"
        group = "historical" if status == "historical" else "active"
        grouped.setdefault(group, []).append(entry)

    for group_entries in grouped.values():
        previous: Decimal | None = None
        for entry in sorted(group_entries, key=lambda e: (e.year, e.created_at or datetime.min)):
            if entry.charge_type == "percent_increase":
                rate = entry.percent_increase
                value = (
                    (previous * (Decimal("1") + rate)).quantize(Decimal("0.01"))
                    if previous is not None and rate is not None
                    else None
                )
            else:
                value = entry.amount
            resolved[entry.id] = value
            if value is not None:
                previous = value
    return resolved


def historical_comparatives(
    entries: Iterable[LeaseCamEntry], *, limit: int = 8
) -> list[dict[str, Any]]:
    """Compact prior-year figures for AI CAM-reconciliation review.

    Gives the reviewer a real multi-year baseline (base rent, CAM, opex,
    true-up) drawn from imported history instead of only the single prior
    reconciliation statement.
    """
    rows = [
        entry for entry in entries if (entry.period_status or "current") == "historical"
    ]
    rows.sort(key=lambda e: e.year, reverse=True)
    comparatives: list[dict[str, Any]] = []
    for entry in rows[:limit]:
        record = {
            "year": entry.year,
            "cam_amount": entry.amount,
            "cam_psf": entry.cam_psf,
            "base_rent_amount": entry.base_rent_amount,
            "base_rent_frequency": entry.base_rent_frequency,
            "operating_expense_amount": entry.operating_expense_amount,
            "reconciliation_true_up": entry.reconciliation_true_up,
        }
        comparatives.append({k: v for k, v in record.items() if v is not None})
    return comparatives
