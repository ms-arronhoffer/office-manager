"""Bank-reconciliation API router (Phase 1.2) — `/api/v1/bank`.

A bank register and statement-reconciliation workflow layered on the audit-grade
general ledger. All endpoints are gated to the ``admin`` and ``accountant`` roles
so finance data stays with finance staff, mirroring the rest of the accounting
surface (GL, AP, AR, CAM).

Workflow:
  1. ``POST /accounts`` registers a bank account mapped to a GL cash account.
  2. ``POST /accounts/{id}/import`` uploads a CSV or OFX/QFX statement; parsed
     transactions are imported into the register (duplicates skipped by FITID).
  3. ``POST /accounts/{id}/reconciliations`` starts a reconciliation for a
     statement (beginning + ending balance).
  4. ``POST /reconciliations/{id}/clear`` marks transactions as cleared; the
     running proof (beginning + cleared == ending) is recomputed.
  5. ``POST /reconciliations/{id}/complete`` locks the reconciliation once it
     ties out (difference is zero).

Amounts are USD-only; FX is deferred. Live bank-feed integration is out of scope
for this phase — file import only.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import require_role
from app.database import get_db
from app.models.bank_account import (
    BankAccount,
    BankReconciliation,
    BankTransaction,
)
from app.models.general_ledger import GLAccount
from app.models.user import User
from app.services import bank_service as svc
from app.services.bank_service import BankError

router = APIRouter()

# Finance staff only.
FinanceUser = require_role("admin", "accountant")

# Cap uploaded statement size to a sane limit (5 MB).
_MAX_UPLOAD_BYTES = 5 * 1024 * 1024


# ─── Schemas ──────────────────────────────────────────────────────────────────

class BankAccountCreate(BaseModel):
    name: str
    gl_account_id: uuid.UUID
    institution: str | None = None
    account_number_last4: str | None = None
    currency: str = "USD"
    notes: str | None = None


class BankAccountUpdate(BaseModel):
    name: str | None = None
    gl_account_id: uuid.UUID | None = None
    institution: str | None = None
    account_number_last4: str | None = None
    is_active: bool | None = None
    notes: str | None = None


class BankAccountResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    name: str
    gl_account_id: uuid.UUID
    gl_account_code: str | None = None
    gl_account_name: str | None = None
    institution: str | None
    account_number_last4: str | None
    currency: str
    is_active: bool
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TransactionCreate(BaseModel):
    txn_date: date
    amount: Decimal
    description: str | None = None
    reference: str | None = None


class TransactionResponse(BaseModel):
    id: uuid.UUID
    bank_account_id: uuid.UUID
    txn_date: date
    description: str | None
    amount: Decimal
    reference: str | None
    fitid: str | None
    import_source: str | None
    status: str
    reconciliation_id: uuid.UUID | None
    journal_entry_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ImportResult(BaseModel):
    imported: int
    skipped: int
    total: int
    source: str


class ReconciliationCreate(BaseModel):
    statement_date: date
    ending_balance: Decimal
    beginning_balance: Decimal | None = None
    notes: str | None = None


class ReconciliationSummary(BaseModel):
    beginning_balance: Decimal
    ending_balance: Decimal
    cleared_deposits: Decimal
    cleared_withdrawals: Decimal
    cleared_balance: Decimal
    difference: Decimal
    is_balanced: bool
    cleared_count: int


class ReconciliationResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    bank_account_id: uuid.UUID
    statement_date: date
    beginning_balance: Decimal
    ending_balance: Decimal
    status: str
    notes: str | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    summary: ReconciliationSummary


class ClearRequest(BaseModel):
    transaction_ids: list[uuid.UUID]


class ReconciliationReport(BaseModel):
    reconciliation: ReconciliationResponse
    cleared_transactions: list[TransactionResponse]
    outstanding_transactions: list[TransactionResponse]
    gl_book_balance: Decimal


# ─── Serialization helpers ────────────────────────────────────────────────────

def _serialize_account(account: BankAccount) -> BankAccountResponse:
    gl = account.gl_account
    return BankAccountResponse(
        id=account.id,
        organization_id=account.organization_id,
        name=account.name,
        gl_account_id=account.gl_account_id,
        gl_account_code=gl.code if gl else None,
        gl_account_name=gl.name if gl else None,
        institution=account.institution,
        account_number_last4=account.account_number_last4,
        currency=account.currency,
        is_active=account.is_active,
        notes=account.notes,
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


def _serialize_reconciliation(recon: BankReconciliation) -> ReconciliationResponse:
    return ReconciliationResponse(
        id=recon.id,
        organization_id=recon.organization_id,
        bank_account_id=recon.bank_account_id,
        statement_date=recon.statement_date,
        beginning_balance=svc._q(recon.beginning_balance),
        ending_balance=svc._q(recon.ending_balance),
        status=recon.status,
        notes=recon.notes,
        completed_at=recon.completed_at,
        created_at=recon.created_at,
        updated_at=recon.updated_at,
        summary=ReconciliationSummary(**svc.reconciliation_summary(recon)),
    )


# ─── Loading helpers ──────────────────────────────────────────────────────────

async def _load_account(db: AsyncSession, account_id: uuid.UUID, org_id) -> BankAccount:
    account = (
        await db.execute(
            select(BankAccount)
            .where(
                BankAccount.id == account_id,
                BankAccount.organization_id == org_id,
            )
            .options(selectinload(BankAccount.gl_account))
        )
    ).scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bank account not found")
    return account


async def _validate_cash_account(db: AsyncSession, gl_account_id: uuid.UUID, org_id) -> GLAccount:
    account = (
        await db.execute(
            select(GLAccount).where(
                GLAccount.id == gl_account_id,
                GLAccount.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unknown GL account.",
        )
    if account.type != "asset":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A bank account must map to an asset (cash) GL account.",
        )
    return account


async def _load_reconciliation(db: AsyncSession, reconciliation_id: uuid.UUID, org_id) -> BankReconciliation:
    db.expunge_all()
    recon = await svc.get_reconciliation(db, reconciliation_id, org_id)
    if not recon:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation not found")
    return recon


# ─── Bank account endpoints ───────────────────────────────────────────────────

@router.get("/accounts", response_model=list[BankAccountResponse])
async def list_accounts(
    active_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    stmt = (
        select(BankAccount)
        .where(BankAccount.organization_id == current_user.organization_id)
        .options(selectinload(BankAccount.gl_account))
        .order_by(BankAccount.name)
    )
    if active_only:
        stmt = stmt.where(BankAccount.is_active.is_(True))
    result = await db.execute(stmt)
    return [_serialize_account(a) for a in result.scalars().unique().all()]


@router.post("/accounts", response_model=BankAccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    payload: BankAccountCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    org_id = current_user.organization_id
    currency = (payload.currency or "USD").upper()
    if currency != "USD":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only USD bank accounts are supported; multi-currency is not yet available.",
        )
    await _validate_cash_account(db, payload.gl_account_id, org_id)
    account = BankAccount(
        organization_id=org_id,
        name=payload.name,
        gl_account_id=payload.gl_account_id,
        institution=payload.institution,
        account_number_last4=payload.account_number_last4,
        currency=currency,
        notes=payload.notes,
    )
    db.add(account)
    await db.commit()
    account = await _load_account(db, account.id, org_id)
    return _serialize_account(account)


@router.get("/accounts/{account_id}", response_model=BankAccountResponse)
async def get_account(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    account = await _load_account(db, account_id, current_user.organization_id)
    return _serialize_account(account)


@router.patch("/accounts/{account_id}", response_model=BankAccountResponse)
async def update_account(
    account_id: uuid.UUID,
    payload: BankAccountUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    org_id = current_user.organization_id
    account = await _load_account(db, account_id, org_id)
    data = payload.model_dump(exclude_unset=True)
    if "gl_account_id" in data and data["gl_account_id"] is not None:
        await _validate_cash_account(db, data["gl_account_id"], org_id)
    for field, value in data.items():
        setattr(account, field, value)
    await db.commit()
    account = await _load_account(db, account.id, org_id)
    return _serialize_account(account)


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    org_id = current_user.organization_id
    account = await _load_account(db, account_id, org_id)
    has_txns = (
        await db.execute(
            select(BankTransaction.id).where(BankTransaction.bank_account_id == account.id).limit(1)
        )
    ).first()
    if has_txns:
        # Preserve financial history: deactivate an account that has activity.
        account.is_active = False
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bank account has transactions and was deactivated instead of deleted.",
        )
    await db.delete(account)
    await db.commit()


# ─── Transaction endpoints ────────────────────────────────────────────────────

@router.get("/accounts/{account_id}/transactions", response_model=list[TransactionResponse])
async def list_transactions(
    account_id: uuid.UUID,
    status_filter: str | None = Query(default=None, alias="status"),
    unreconciled_only: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    await _load_account(db, account_id, current_user.organization_id)
    stmt = (
        select(BankTransaction)
        .where(BankTransaction.bank_account_id == account_id)
        .order_by(BankTransaction.txn_date.desc(), BankTransaction.created_at.desc())
    )
    if status_filter:
        stmt = stmt.where(BankTransaction.status == status_filter)
    if unreconciled_only:
        stmt = stmt.where(BankTransaction.reconciliation_id.is_(None))
    result = await db.execute(stmt)
    return [TransactionResponse.model_validate(t) for t in result.scalars().all()]


@router.post(
    "/accounts/{account_id}/transactions",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_transaction(
    account_id: uuid.UUID,
    payload: TransactionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Manually add a single bank-register line (signed amount)."""
    org_id = current_user.organization_id
    await _load_account(db, account_id, org_id)
    if svc._q(payload.amount) == Decimal("0.00"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Transaction amount cannot be zero.",
        )
    txn = BankTransaction(
        organization_id=org_id,
        bank_account_id=account_id,
        txn_date=payload.txn_date,
        description=payload.description,
        amount=svc._q(payload.amount),
        reference=payload.reference,
        import_source="manual",
        status="unmatched",
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)
    return TransactionResponse.model_validate(txn)


@router.post("/accounts/{account_id}/import", response_model=ImportResult)
async def import_statement(
    account_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Upload a CSV or OFX/QFX statement and import its transactions."""
    org_id = current_user.organization_id
    account = await _load_account(db, account_id, org_id)
    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The uploaded file is empty.",
        )
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="The uploaded file is too large (max 5 MB).",
        )
    try:
        transactions, source = svc.parse_statement(content, file.filename)
        result = await svc.import_transactions(
            db, org_id, account, transactions, source=source
        )
    except BankError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    return ImportResult(source=source, **result)


@router.delete("/transactions/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transaction(
    transaction_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    txn = (
        await db.execute(
            select(BankTransaction).where(
                BankTransaction.id == transaction_id,
                BankTransaction.organization_id == current_user.organization_id,
            )
        )
    ).scalar_one_or_none()
    if not txn:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    if txn.reconciliation_id is not None or txn.status == "cleared":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A cleared transaction cannot be deleted; unclear it first.",
        )
    await db.delete(txn)
    await db.commit()


# ─── Reconciliation endpoints ─────────────────────────────────────────────────

@router.get("/accounts/{account_id}/reconciliations", response_model=list[ReconciliationResponse])
async def list_reconciliations(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    await _load_account(db, account_id, current_user.organization_id)
    result = await db.execute(
        select(BankReconciliation)
        .where(BankReconciliation.bank_account_id == account_id)
        .options(selectinload(BankReconciliation.transactions))
        .order_by(BankReconciliation.statement_date.desc())
    )
    return [_serialize_reconciliation(r) for r in result.scalars().unique().all()]


@router.post(
    "/accounts/{account_id}/reconciliations",
    response_model=ReconciliationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_reconciliation(
    account_id: uuid.UUID,
    payload: ReconciliationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Start a reconciliation for a statement period."""
    org_id = current_user.organization_id
    await _load_account(db, account_id, org_id)
    beginning = payload.beginning_balance
    if beginning is None:
        beginning = await svc.suggested_beginning_balance(db, org_id, account_id)
    recon = BankReconciliation(
        organization_id=org_id,
        bank_account_id=account_id,
        statement_date=payload.statement_date,
        beginning_balance=svc._q(beginning),
        ending_balance=svc._q(payload.ending_balance),
        notes=payload.notes,
        status="in_progress",
    )
    db.add(recon)
    await db.commit()
    recon = await _load_reconciliation(db, recon.id, org_id)
    return _serialize_reconciliation(recon)


@router.get("/reconciliations/{reconciliation_id}", response_model=ReconciliationReport)
async def get_reconciliation_report(
    reconciliation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Full balance proof: cleared items, outstanding items, and GL book balance."""
    org_id = current_user.organization_id
    recon = await _load_reconciliation(db, reconciliation_id, org_id)
    account = await _load_account(db, recon.bank_account_id, org_id)

    cleared = sorted(recon.transactions, key=lambda t: (t.txn_date, t.created_at))
    outstanding = (
        await db.execute(
            select(BankTransaction)
            .where(
                BankTransaction.bank_account_id == recon.bank_account_id,
                BankTransaction.reconciliation_id.is_(None),
                BankTransaction.txn_date <= recon.statement_date,
            )
            .order_by(BankTransaction.txn_date, BankTransaction.created_at)
        )
    ).scalars().all()

    book_balance = await svc.gl_book_balance(
        db, org_id, account.gl_account_id, as_of=recon.statement_date
    )
    return ReconciliationReport(
        reconciliation=_serialize_reconciliation(recon),
        cleared_transactions=[TransactionResponse.model_validate(t) for t in cleared],
        outstanding_transactions=[TransactionResponse.model_validate(t) for t in outstanding],
        gl_book_balance=book_balance,
    )


def _ensure_in_progress(recon: BankReconciliation) -> None:
    if recon.status != "in_progress":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A completed reconciliation must be reopened before it can be edited.",
        )


@router.post("/reconciliations/{reconciliation_id}/clear", response_model=ReconciliationResponse)
async def clear_transactions(
    reconciliation_id: uuid.UUID,
    payload: ClearRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Mark the given transactions as cleared into this reconciliation."""
    org_id = current_user.organization_id
    recon = await _load_reconciliation(db, reconciliation_id, org_id)
    _ensure_in_progress(recon)
    if not payload.transaction_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No transactions were provided to clear.",
        )
    txns = (
        await db.execute(
            select(BankTransaction).where(
                BankTransaction.id.in_(payload.transaction_ids),
                BankTransaction.bank_account_id == recon.bank_account_id,
            )
        )
    ).scalars().all()
    found = {t.id for t in txns}
    missing = set(payload.transaction_ids) - found
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction(s) not found on this account: {', '.join(str(m) for m in missing)}.",
        )
    for txn in txns:
        if txn.reconciliation_id not in (None, recon.id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A transaction is already cleared in another reconciliation.",
            )
        txn.reconciliation_id = recon.id
        txn.status = "cleared"
    await db.commit()
    recon = await _load_reconciliation(db, recon.id, org_id)
    return _serialize_reconciliation(recon)


@router.post("/reconciliations/{reconciliation_id}/unclear", response_model=ReconciliationResponse)
async def unclear_transactions(
    reconciliation_id: uuid.UUID,
    payload: ClearRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Remove the given transactions from this reconciliation (back to outstanding)."""
    org_id = current_user.organization_id
    recon = await _load_reconciliation(db, reconciliation_id, org_id)
    _ensure_in_progress(recon)
    txns = (
        await db.execute(
            select(BankTransaction).where(
                BankTransaction.id.in_(payload.transaction_ids),
                BankTransaction.reconciliation_id == recon.id,
            )
        )
    ).scalars().all()
    for txn in txns:
        txn.reconciliation_id = None
        txn.status = "unmatched"
    await db.commit()
    recon = await _load_reconciliation(db, recon.id, org_id)
    return _serialize_reconciliation(recon)


@router.post("/reconciliations/{reconciliation_id}/complete", response_model=ReconciliationResponse)
async def complete_reconciliation(
    reconciliation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Lock a reconciliation once its cleared activity ties out to the statement."""
    org_id = current_user.organization_id
    recon = await _load_reconciliation(db, reconciliation_id, org_id)
    if recon.status == "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reconciliation is already completed.",
        )
    if not svc.is_balanced(recon):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Reconciliation does not balance: the cleared balance must equal "
                f"the statement ending balance (difference {svc.difference(recon)})."
            ),
        )
    recon.status = "completed"
    recon.completed_at = datetime.now(timezone.utc)
    recon.completed_by_id = current_user.id
    await db.commit()
    recon = await _load_reconciliation(db, recon.id, org_id)
    return _serialize_reconciliation(recon)


@router.post("/reconciliations/{reconciliation_id}/reopen", response_model=ReconciliationResponse)
async def reopen_reconciliation(
    reconciliation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Reopen a completed reconciliation for further edits."""
    org_id = current_user.organization_id
    recon = await _load_reconciliation(db, reconciliation_id, org_id)
    if recon.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a completed reconciliation can be reopened.",
        )
    recon.status = "in_progress"
    recon.completed_at = None
    recon.completed_by_id = None
    await db.commit()
    recon = await _load_reconciliation(db, recon.id, org_id)
    return _serialize_reconciliation(recon)


@router.delete("/reconciliations/{reconciliation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reconciliation(
    reconciliation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    org_id = current_user.organization_id
    recon = await _load_reconciliation(db, reconciliation_id, org_id)
    if recon.status == "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A completed reconciliation must be reopened before it can be deleted.",
        )
    # Release any cleared transactions back to outstanding before removing.
    for txn in recon.transactions:
        txn.reconciliation_id = None
        txn.status = "unmatched"
    await db.delete(recon)
    await db.commit()
