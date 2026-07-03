"""Budgeting API router (Phase 1.4) — `/api/v1/budgets`.

GL-account-level annual budgets and their budget-vs-actual variance report.
Budgets are managed by finance staff (``admin`` / ``accountant``); actuals are
read live from the general ledger at report time, so budgets never post to the
GL.

Workflow:
  1. ``POST /`` creates a budget for a fiscal year with per-account lines.
  2. ``PATCH /{id}`` edits the header and/or replaces the lines.
  3. ``GET /{id}/report?as_of=YYYY-MM-DD`` returns budget-vs-actual variance.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import require_role
from app.database import get_db
from app.models.budget import BUDGET_STATUSES, Budget, BudgetLine
from app.models.general_ledger import GLAccount
from app.models.user import User
from app.services import budget_service as svc

router = APIRouter()

# Finance staff only.
FinanceUser = require_role("admin", "accountant")


# ─── Schemas ────────────────────────────────────────────────────────────────

class BudgetLineInput(BaseModel):
    account_id: uuid.UUID
    amount: Decimal
    notes: str | None = None


class BudgetCreate(BaseModel):
    name: str
    fiscal_year: int
    status: str = "draft"
    notes: str | None = None
    lines: list[BudgetLineInput] = []


class BudgetUpdate(BaseModel):
    name: str | None = None
    fiscal_year: int | None = None
    status: str | None = None
    notes: str | None = None
    lines: list[BudgetLineInput] | None = None


class BudgetLineResponse(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    account_code: str | None = None
    account_name: str | None = None
    amount: Decimal
    notes: str | None

    model_config = {"from_attributes": True}


class BudgetResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    name: str
    fiscal_year: int
    status: str
    notes: str | None
    total_amount: Decimal
    created_at: datetime
    updated_at: datetime
    lines: list[BudgetLineResponse]


class VarianceRow(BaseModel):
    account_id: uuid.UUID
    code: str
    name: str
    type: str
    budget: Decimal
    actual: Decimal
    variance: Decimal
    variance_pct: float | None


class BudgetReport(BaseModel):
    budget_id: uuid.UUID
    name: str
    fiscal_year: int
    as_of: date
    total_budget: Decimal
    total_actual: Decimal
    total_variance: Decimal
    rows: list[VarianceRow]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _serialize(budget: Budget) -> BudgetResponse:
    lines = []
    total = Decimal("0.00")
    for line in budget.lines:
        total += line.amount or Decimal("0")
        lines.append(
            BudgetLineResponse(
                id=line.id,
                account_id=line.account_id,
                account_code=line.account.code if line.account else None,
                account_name=line.account.name if line.account else None,
                amount=line.amount,
                notes=line.notes,
            )
        )
    return BudgetResponse(
        id=budget.id,
        organization_id=budget.organization_id,
        name=budget.name,
        fiscal_year=budget.fiscal_year,
        status=budget.status,
        notes=budget.notes,
        total_amount=total,
        created_at=budget.created_at,
        updated_at=budget.updated_at,
        lines=lines,
    )


def _validate_status(status_value: str) -> str:
    if status_value not in BUDGET_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"status must be one of: {', '.join(sorted(BUDGET_STATUSES))}.",
        )
    return status_value


async def _validate_accounts(db: AsyncSession, account_ids: set[uuid.UUID], org_id) -> None:
    if not account_ids:
        return
    found = (
        await db.execute(
            select(GLAccount.id).where(
                GLAccount.id.in_(account_ids),
                GLAccount.organization_id == org_id,
            )
        )
    ).scalars().all()
    missing = account_ids - set(found)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown account id(s): {', '.join(str(m) for m in missing)}.",
        )


def _validate_lines(lines: list[BudgetLineInput]) -> None:
    seen: set[uuid.UUID] = set()
    for line in lines:
        if line.account_id in seen:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Each account may appear at most once in a budget.",
            )
        seen.add(line.account_id)


def _set_lines(budget: Budget, lines: list[BudgetLineInput]) -> None:
    budget.lines.clear()
    for line in lines:
        budget.lines.append(
            BudgetLine(
                account_id=line.account_id,
                amount=line.amount,
                notes=line.notes,
            )
        )


async def _load(db: AsyncSession, budget_id: uuid.UUID, org_id) -> Budget:
    db.expunge_all()
    budget = await svc.get_budget(db, budget_id, org_id)
    if not budget:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Budget not found")
    return budget


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=list[BudgetResponse])
async def list_budgets(
    fiscal_year: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    stmt = (
        select(Budget)
        .where(Budget.organization_id == current_user.organization_id)
        .options(selectinload(Budget.lines).selectinload(BudgetLine.account))
        .order_by(Budget.fiscal_year.desc(), Budget.name)
    )
    if fiscal_year is not None:
        stmt = stmt.where(Budget.fiscal_year == fiscal_year)
    result = await db.execute(stmt)
    return [_serialize(b) for b in result.scalars().unique().all()]


@router.get("/{budget_id}", response_model=BudgetResponse)
async def get_budget(
    budget_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    budget = await _load(db, budget_id, current_user.organization_id)
    return _serialize(budget)


@router.post("", response_model=BudgetResponse, status_code=status.HTTP_201_CREATED)
async def create_budget(
    payload: BudgetCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    org_id = current_user.organization_id
    _validate_status(payload.status)
    _validate_lines(payload.lines)
    await _validate_accounts(db, {line.account_id for line in payload.lines}, org_id)

    existing = (
        await db.execute(
            select(Budget.id).where(
                Budget.organization_id == org_id,
                Budget.fiscal_year == payload.fiscal_year,
                Budget.name == payload.name,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A budget with this name already exists for the fiscal year.",
        )

    budget = Budget(
        organization_id=org_id,
        name=payload.name,
        fiscal_year=payload.fiscal_year,
        status=payload.status,
        notes=payload.notes,
    )
    _set_lines(budget, payload.lines)
    db.add(budget)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A budget with this name already exists for the fiscal year.",
        )
    budget = await _load(db, budget.id, org_id)
    return _serialize(budget)


@router.patch("/{budget_id}", response_model=BudgetResponse)
async def update_budget(
    budget_id: uuid.UUID,
    payload: BudgetUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    org_id = current_user.organization_id
    budget = await _load(db, budget_id, org_id)

    data = payload.model_dump(exclude_unset=True)
    for field in ("name", "fiscal_year", "notes"):
        if field in data:
            setattr(budget, field, data[field])
    if "status" in data:
        budget.status = _validate_status(data["status"])
    if payload.lines is not None:
        _validate_lines(payload.lines)
        await _validate_accounts(db, {line.account_id for line in payload.lines}, org_id)
        _set_lines(budget, payload.lines)

    await db.commit()
    budget = await _load(db, budget.id, org_id)
    return _serialize(budget)


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_budget(
    budget_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    budget = await _load(db, budget_id, current_user.organization_id)
    await db.delete(budget)
    await db.commit()


@router.get("/{budget_id}/report", response_model=BudgetReport)
async def budget_report(
    budget_id: uuid.UUID,
    as_of: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Budget-vs-actual variance for the budget, optionally clamped to ``as_of``."""
    budget = await _load(db, budget_id, current_user.organization_id)
    report = await svc.budget_vs_actual(
        db, current_user.organization_id, budget, as_of=as_of
    )
    return BudgetReport(
        budget_id=report["budget_id"],
        name=report["name"],
        fiscal_year=report["fiscal_year"],
        as_of=report["as_of"],
        total_budget=report["total_budget"],
        total_actual=report["total_actual"],
        total_variance=report["total_variance"],
        rows=[VarianceRow(**r) for r in report["rows"]],
    )
