"""Owner / trust accounting service layer (Phase 2.6).

Holds the owner-money rules so the ``/api/v1/owners`` and owner-portal routers
stay thin. The owner ledger is the source of truth for what the manager owes
each owner; every movement also posts a matching double-entry into the shared
general ledger so trust balances reconcile with the GL:

  * income        — ``Dr Trust Cash / Cr Due to Owners``  (balance ↑)
  * expense       — ``Dr Due to Owners / Cr Trust Cash``  (balance ↓)
  * management fee — ``Dr Due to Owners / Cr Management Fee Income`` (balance ↓)
  * distribution  — ``Dr Due to Owners / Cr Cash``        (balance ↓)

Ledger amounts are stored *signed* (positive = owed to the owner) so an owner
statement is a straight running sum. Distributions are created ``pending`` and
only post their ledger + GL entries when marked ``paid``. Trust/escrow accounts
carry a compliance-review workflow; a ``flagged`` account blocks payouts.

All amounts are USD. GL postings reuse :mod:`app.services.gl_service` so owner
money lands in the same audit-grade ledger as lease, CAM, AR, AP, and rent.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.general_ledger import GLAccount
from app.models.office import Office
from app.models.owner import (
    OwnerDistribution,
    OwnerLedgerEntry,
    OwnerProperty,
    PropertyOwner,
    TrustAccount,
)
from app.services import gl_service

TWO = Decimal("0.01")

# GL source tag carried on owner-sourced journal entries.
OWNER_GL_SOURCE = "owner"

# Feature-specific accounts ensured present before posting owner entries.
OWNER_ACCOUNTS: list[tuple[str, str, str]] = [
    ("1050", "Trust Cash", "asset"),
    ("2500", "Due to Owners", "liability"),
    ("4500", "Management Fee Income", "revenue"),
]

# Account codes used by owner postings.
TRUST_CASH_CODE = "1050"
DUE_TO_OWNERS_CODE = "2500"
MANAGEMENT_FEE_INCOME_CODE = "4500"
CASH_CODE = "1000"

# Signed multiplier applied to the natural (positive) amount for each ledger
# type. ``adjustment`` is signed by the caller so it is not listed here.
_ENTRY_SIGN = {
    "income": Decimal("1"),
    "expense": Decimal("-1"),
    "management_fee": Decimal("-1"),
    "distribution": Decimal("-1"),
}


class OwnerError(ValueError):
    """Raised for owner/trust accounting rule violations."""


def _q(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(TWO, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Account helpers
# ---------------------------------------------------------------------------

async def ensure_owner_accounts(
    db: AsyncSession, organization_id: uuid.UUID | None
) -> None:
    """Make sure the trust/owner GL accounts exist for the org."""
    await gl_service.seed_default_accounts(db, organization_id)
    await gl_service.ensure_accounts(db, organization_id, OWNER_ACCOUNTS, commit=False)


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
        raise OwnerError(f"GL account with code {code} is not configured.")
    return acct


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

async def load_owner(
    db: AsyncSession, organization_id: uuid.UUID | None, owner_id: uuid.UUID
) -> PropertyOwner:
    owner = (
        await db.execute(
            select(PropertyOwner).where(
                PropertyOwner.id == owner_id,
                PropertyOwner.organization_id == organization_id,
                PropertyOwner.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if owner is None:
        raise OwnerError("Owner not found.")
    return owner


async def load_trust_account(
    db: AsyncSession, organization_id: uuid.UUID | None, trust_account_id: uuid.UUID
) -> TrustAccount:
    account = (
        await db.execute(
            select(TrustAccount).where(
                TrustAccount.id == trust_account_id,
                TrustAccount.organization_id == organization_id,
                TrustAccount.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if account is None:
        raise OwnerError("Trust account not found.")
    return account


# ---------------------------------------------------------------------------
# Property links
# ---------------------------------------------------------------------------

async def assign_property(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    owner: PropertyOwner,
    *,
    office_id: uuid.UUID,
    ownership_percent: Decimal | None = None,
    management_fee_percent: Decimal | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> OwnerProperty:
    """Link an owner to a property (office), rejecting duplicates."""
    office = (
        await db.execute(
            select(Office).where(
                Office.id == office_id,
                Office.organization_id == organization_id,
            )
        )
    ).scalar_one_or_none()
    if office is None:
        raise OwnerError("Property (office) not found.")

    existing = (
        await db.execute(
            select(OwnerProperty).where(
                OwnerProperty.owner_id == owner.id,
                OwnerProperty.office_id == office_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise OwnerError("Owner is already linked to this property.")

    pct = _pct(ownership_percent, default=Decimal("100"))
    link = OwnerProperty(
        organization_id=organization_id,
        owner_id=owner.id,
        office_id=office_id,
        ownership_percent=pct,
        management_fee_percent=(
            _pct(management_fee_percent) if management_fee_percent is not None else None
        ),
        start_date=start_date,
        end_date=end_date,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return link


def _pct(value, *, default: Decimal | None = None) -> Decimal:
    if value is None:
        if default is None:
            raise OwnerError("A percentage is required.")
        return default
    pct = Decimal(str(value))
    if pct < 0 or pct > 100:
        raise OwnerError("Percentage must be between 0 and 100.")
    return pct.quantize(TWO, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

async def owner_balance(
    db: AsyncSession, organization_id: uuid.UUID | None, owner_id: uuid.UUID
) -> Decimal:
    """Return the current balance owed to an owner (sum of signed ledger lines)."""
    entries = (
        await db.execute(
            select(OwnerLedgerEntry.amount).where(
                OwnerLedgerEntry.organization_id == organization_id,
                OwnerLedgerEntry.owner_id == owner_id,
            )
        )
    ).scalars().all()
    return _q(sum((e for e in entries), Decimal("0")))


async def _post_ledger_gl(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    *,
    entry_type: str,
    amount: Decimal,
    entry_date: date,
    owner: PropertyOwner,
    memo: str | None,
    posted_by_id: uuid.UUID | None,
    distribution_credit_code: str = CASH_CODE,
) -> uuid.UUID | None:
    """Post the double-entry GL journal for a ledger movement; returns its id."""
    legs: list[tuple[str, str]] | None
    if entry_type == "income":
        legs = [(TRUST_CASH_CODE, "debit"), (DUE_TO_OWNERS_CODE, "credit")]
    elif entry_type == "expense":
        legs = [(DUE_TO_OWNERS_CODE, "debit"), (TRUST_CASH_CODE, "credit")]
    elif entry_type == "management_fee":
        legs = [(DUE_TO_OWNERS_CODE, "debit"), (MANAGEMENT_FEE_INCOME_CODE, "credit")]
    elif entry_type == "distribution":
        legs = [(DUE_TO_OWNERS_CODE, "debit"), (distribution_credit_code, "credit")]
    else:  # adjustment and anything else: no GL side.
        return None

    lines = []
    for code, side in legs:
        acct = await _account_by_code(db, organization_id, code)
        lines.append(
            {
                "account_id": acct.id,
                "debit": amount if side == "debit" else Decimal("0"),
                "credit": amount if side == "credit" else Decimal("0"),
            }
        )
    entry = await gl_service.create_journal_entry(
        db,
        organization_id,
        entry_date=entry_date,
        lines=lines,
        memo=memo or f"Owner {entry_type}: {owner.name}",
        source=OWNER_GL_SOURCE,
        source_ref=str(owner.id),
        posted_by_id=posted_by_id,
        commit=False,
    )
    return entry.id


async def record_ledger_entry(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    owner: PropertyOwner,
    *,
    entry_type: str,
    amount: Decimal,
    entry_date: date | None = None,
    office_id: uuid.UUID | None = None,
    description: str | None = None,
    source: str | None = None,
    source_ref: str | None = None,
    post_gl: bool = True,
    posted_by_id: uuid.UUID | None = None,
    commit: bool = True,
) -> OwnerLedgerEntry:
    """Record a signed owner-ledger line, optionally posting the matching GL entry.

    For fixed-sign types (income/expense/management_fee/distribution) ``amount``
    is the natural positive magnitude and the sign is derived. For ``adjustment``
    the caller passes a signed ``amount`` (positive raises the balance, negative
    lowers it) and no GL entry is posted.
    """
    entry_date = entry_date or date.today()
    magnitude = _q(abs(amount))
    if magnitude <= 0:
        raise OwnerError("Amount must be greater than zero.")

    if entry_type == "adjustment":
        signed = _q(amount)
        if signed == 0:
            raise OwnerError("Adjustment amount must be non-zero.")
    elif entry_type in _ENTRY_SIGN:
        signed = _q(magnitude * _ENTRY_SIGN[entry_type])
    else:
        raise OwnerError(f"Unknown ledger entry type '{entry_type}'.")

    journal_entry_id: uuid.UUID | None = None
    if post_gl and entry_type != "adjustment":
        await ensure_owner_accounts(db, organization_id)
        journal_entry_id = await _post_ledger_gl(
            db,
            organization_id,
            entry_type=entry_type,
            amount=magnitude,
            entry_date=entry_date,
            owner=owner,
            memo=description,
            posted_by_id=posted_by_id,
        )

    entry = OwnerLedgerEntry(
        organization_id=organization_id,
        owner_id=owner.id,
        office_id=office_id,
        entry_date=entry_date,
        entry_type=entry_type,
        amount=signed,
        description=description,
        currency=owner.currency,
        source=source,
        source_ref=source_ref,
        journal_entry_id=journal_entry_id,
    )
    db.add(entry)
    if commit:
        await db.commit()
        await db.refresh(entry)
    else:
        await db.flush()
    return entry


# ---------------------------------------------------------------------------
# Distributions / payouts
# ---------------------------------------------------------------------------

async def create_distribution(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    owner: PropertyOwner,
    *,
    amount: Decimal,
    distribution_date: date | None = None,
    method: str = "ach",
    reference: str | None = None,
    memo: str | None = None,
    trust_account_id: uuid.UUID | None = None,
) -> OwnerDistribution:
    """Create a ``pending`` distribution. Ledger/GL post on :func:`mark_distribution_paid`."""
    amt = _q(amount)
    if amt <= 0:
        raise OwnerError("Distribution amount must be greater than zero.")

    if trust_account_id is not None:
        # Validate the trust account belongs to the org and is not flagged.
        account = await load_trust_account(db, organization_id, trust_account_id)
        if account.compliance_status == "flagged":
            raise OwnerError(
                "Trust account is flagged for compliance review; payouts are blocked."
            )

    dist = OwnerDistribution(
        organization_id=organization_id,
        owner_id=owner.id,
        distribution_date=distribution_date or date.today(),
        amount=amt,
        method=method,
        reference=reference,
        memo=memo,
        currency=owner.currency,
        trust_account_id=trust_account_id,
        status="pending",
    )
    db.add(dist)
    await db.commit()
    await db.refresh(dist)
    return dist


async def mark_distribution_paid(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    distribution: OwnerDistribution,
    *,
    posted_by_id: uuid.UUID | None = None,
) -> OwnerDistribution:
    """Mark a distribution paid, posting its ledger line and GL journal entry."""
    if distribution.status == "paid":
        raise OwnerError("Distribution is already paid.")
    if distribution.status == "void":
        raise OwnerError("Cannot pay a voided distribution.")

    if distribution.trust_account_id is not None:
        account = await load_trust_account(
            db, organization_id, distribution.trust_account_id
        )
        if account.compliance_status == "flagged":
            raise OwnerError(
                "Trust account is flagged for compliance review; payouts are blocked."
            )

    owner = await load_owner(db, organization_id, distribution.owner_id)
    credit_code = TRUST_CASH_CODE if distribution.trust_account_id else CASH_CODE

    await ensure_owner_accounts(db, organization_id)
    journal_entry_id = await _post_ledger_gl(
        db,
        organization_id,
        entry_type="distribution",
        amount=_q(distribution.amount),
        entry_date=distribution.distribution_date,
        owner=owner,
        memo=distribution.memo or f"Owner distribution: {owner.name}",
        posted_by_id=posted_by_id,
        distribution_credit_code=credit_code,
    )

    ledger = OwnerLedgerEntry(
        organization_id=organization_id,
        owner_id=owner.id,
        entry_date=distribution.distribution_date,
        entry_type="distribution",
        amount=_q(-abs(distribution.amount)),
        description=distribution.memo or "Owner distribution",
        currency=distribution.currency,
        source="distribution",
        source_ref=str(distribution.id),
        journal_entry_id=journal_entry_id,
    )
    db.add(ledger)
    await db.flush()

    distribution.status = "paid"
    distribution.ledger_entry_id = ledger.id
    distribution.journal_entry_id = journal_entry_id
    await db.commit()
    await db.refresh(distribution)
    return distribution


async def void_distribution(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    distribution: OwnerDistribution,
) -> OwnerDistribution:
    """Void a ``pending`` distribution. Paid distributions cannot be voided."""
    if distribution.status == "paid":
        raise OwnerError("Cannot void a paid distribution.")
    if distribution.status == "void":
        return distribution
    distribution.status = "void"
    await db.commit()
    await db.refresh(distribution)
    return distribution


# ---------------------------------------------------------------------------
# Statements
# ---------------------------------------------------------------------------

async def generate_statement(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    owner: PropertyOwner,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    """Build an owner statement: opening/closing balances and period activity.

    ``opening_balance`` is the running balance of all ledger lines strictly
    before ``start_date``; the period lines fall within ``[start_date, end_date]``.
    """
    stmt = select(OwnerLedgerEntry).where(
        OwnerLedgerEntry.organization_id == organization_id,
        OwnerLedgerEntry.owner_id == owner.id,
    )
    entries = (
        (await db.execute(stmt.order_by(OwnerLedgerEntry.entry_date, OwnerLedgerEntry.created_at)))
        .scalars()
        .all()
    )

    opening = Decimal("0")
    period_lines: list[OwnerLedgerEntry] = []
    totals = {t: Decimal("0") for t in ("income", "expense", "management_fee", "distribution", "adjustment")}

    for e in entries:
        if start_date is not None and e.entry_date < start_date:
            opening += e.amount
            continue
        if end_date is not None and e.entry_date > end_date:
            continue
        period_lines.append(e)
        totals[e.entry_type] = totals.get(e.entry_type, Decimal("0")) + e.amount

    period_net = sum((e.amount for e in period_lines), Decimal("0"))
    closing = _q(opening + period_net)

    return {
        "owner_id": owner.id,
        "owner_name": owner.name,
        "currency": owner.currency,
        "start_date": start_date,
        "end_date": end_date,
        "opening_balance": _q(opening),
        "closing_balance": closing,
        "totals": {k: _q(v) for k, v in totals.items()},
        "lines": period_lines,
    }


# ---------------------------------------------------------------------------
# Trust accounts — compliance review
# ---------------------------------------------------------------------------

async def review_trust_account(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    account: TrustAccount,
    *,
    compliance_status: str,
    notes: str | None,
    reviewed_by_id: uuid.UUID | None,
) -> TrustAccount:
    """Record a compliance-review decision on a trust/escrow account."""
    from datetime import datetime, timezone

    from app.models.owner import COMPLIANCE_STATUSES

    if compliance_status not in COMPLIANCE_STATUSES:
        raise OwnerError(
            f"Invalid compliance status. Must be one of: {', '.join(COMPLIANCE_STATUSES)}."
        )
    account.compliance_status = compliance_status
    account.compliance_notes = notes
    account.compliance_reviewed_at = datetime.now(timezone.utc)
    account.compliance_reviewed_by_id = reviewed_by_id
    # Once a decision other than the initial "pending" has been recorded, the
    # required-review flag is satisfied for approved accounts.
    if compliance_status == "approved":
        account.compliance_review_required = False
    await db.commit()
    await db.refresh(account)
    return account
