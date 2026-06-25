import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.lease import Lease
from app.models.operating_expense import OperatingExpense
from app.models.user import User

router = APIRouter()

VALID_CATEGORIES = {"cam", "insurance", "taxes", "utilities", "other"}


class OperatingExpenseCreate(BaseModel):
    lease_id: uuid.UUID
    year: int
    category: str
    budgeted: Decimal | None = None
    actual: Decimal | None = None
    notes: str | None = None
    reconciled_at: datetime | None = None


class OperatingExpenseUpdate(BaseModel):
    year: int | None = None
    category: str | None = None
    budgeted: Decimal | None = None
    actual: Decimal | None = None
    notes: str | None = None
    reconciled_at: datetime | None = None


class OperatingExpenseResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None
    lease_id: uuid.UUID
    year: int
    category: str
    budgeted: Decimal | None
    actual: Decimal | None
    notes: str | None
    reconciled_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class VarianceSummary(BaseModel):
    year: int
    category: str
    budgeted: Decimal | None
    actual: Decimal | None
    variance: Decimal | None


@router.get("", response_model=list[OperatingExpenseResponse])
async def list_expenses(
    lease_id: uuid.UUID | None = Query(default=None),
    year: int | None = Query(default=None),
    category: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(OperatingExpense).where(
        OperatingExpense.organization_id == current_user.organization_id
    )
    if lease_id:
        stmt = stmt.where(OperatingExpense.lease_id == lease_id)
    if year:
        stmt = stmt.where(OperatingExpense.year == year)
    if category:
        stmt = stmt.where(OperatingExpense.category == category)
    stmt = stmt.order_by(OperatingExpense.year.desc(), OperatingExpense.category)
    result = await db.execute(stmt)
    return [OperatingExpenseResponse.model_validate(e) for e in result.scalars().all()]


@router.post("", response_model=OperatingExpenseResponse, status_code=status.HTTP_201_CREATED)
async def create_expense(
    payload: OperatingExpenseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    # Verify lease belongs to org
    lease = (await db.execute(
        select(Lease).where(
            Lease.id == payload.lease_id,
            Lease.organization_id == current_user.organization_id,
        )
    )).scalar_one_or_none()
    if not lease:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lease not found")

    expense = OperatingExpense(
        **payload.model_dump(),
        organization_id=current_user.organization_id,
    )
    db.add(expense)
    await db.commit()
    await db.refresh(expense)
    return OperatingExpenseResponse.model_validate(expense)


@router.patch("/{expense_id}", response_model=OperatingExpenseResponse)
async def update_expense(
    expense_id: uuid.UUID,
    payload: OperatingExpenseUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    result = await db.execute(
        select(OperatingExpense).where(
            OperatingExpense.id == expense_id,
            OperatingExpense.organization_id == current_user.organization_id,
        )
    )
    expense = result.scalar_one_or_none()
    if not expense:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(expense, field, value)

    await db.commit()
    await db.refresh(expense)
    return OperatingExpenseResponse.model_validate(expense)


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_expense(
    expense_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    result = await db.execute(
        select(OperatingExpense).where(
            OperatingExpense.id == expense_id,
            OperatingExpense.organization_id == current_user.organization_id,
        )
    )
    expense = result.scalar_one_or_none()
    if not expense:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expense not found")
    await db.delete(expense)
    await db.commit()


@router.get("/variance", response_model=list[VarianceSummary])
async def get_variance(
    lease_id: uuid.UUID | None = Query(default=None),
    year: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Budget vs. actual variance by year and category."""
    stmt = select(OperatingExpense).where(
        OperatingExpense.organization_id == current_user.organization_id
    )
    if lease_id:
        stmt = stmt.where(OperatingExpense.lease_id == lease_id)
    if year:
        stmt = stmt.where(OperatingExpense.year == year)
    stmt = stmt.order_by(OperatingExpense.year.desc(), OperatingExpense.category)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    summaries = []
    for row in rows:
        variance = None
        if row.actual is not None and row.budgeted is not None:
            variance = row.actual - row.budgeted
        summaries.append(VarianceSummary(
            year=row.year,
            category=row.category,
            budgeted=row.budgeted,
            actual=row.actual,
            variance=variance,
        ))
    return summaries
