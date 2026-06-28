"""Financial-statements API router (Phase 6 + Phase 7) — `/api/v1/financials`.

GAAP financial statements derived from the audit-grade general ledger:

  - ``GET /income-statement`` — revenue less expenses over a period (P&L).
  - ``GET /balance-sheet`` — assets, liabilities and equity as of a date.
  - ``GET /cash-flow-statement`` — operating / investing / financing cash flows
    over a period, reconciling beginning to ending cash.

All reports accept optional ``year`` and ``month`` query params (a single
month, a whole year, or — when omitted — all activity to date). Like the rest of
the accounting surface, the endpoints are gated to the ``admin`` and
``accountant`` roles so finance data stays with finance staff.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.database import get_db
from app.models.user import User
from app.services import financials_service as svc

router = APIRouter()

# Finance staff only.
FinanceUser = require_role("admin", "accountant")


# ─── Schemas ──────────────────────────────────────────────────────────────────

class StatementLine(BaseModel):
    account_id: uuid.UUID | None
    code: str
    name: str
    amount: Decimal


class IncomeStatementResponse(BaseModel):
    start_date: date | None
    end_date: date | None
    revenue: list[StatementLine]
    total_revenue: Decimal
    expenses: list[StatementLine]
    total_expenses: Decimal
    net_income: Decimal


class BalanceSheetResponse(BaseModel):
    as_of_date: date | None
    assets: list[StatementLine]
    total_assets: Decimal
    liabilities: list[StatementLine]
    total_liabilities: Decimal
    equity: list[StatementLine]
    total_equity: Decimal
    liabilities_and_equity: Decimal
    net_income: Decimal
    balanced: bool


class CashFlowSection(BaseModel):
    lines: list[StatementLine]
    total: Decimal


class CashFlowStatementResponse(BaseModel):
    start_date: date | None
    end_date: date | None
    operating: CashFlowSection
    investing: CashFlowSection
    financing: CashFlowSection
    net_change_in_cash: Decimal
    beginning_cash: Decimal
    ending_cash: Decimal


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/income-statement", response_model=IncomeStatementResponse)
async def get_income_statement(
    year: int | None = Query(default=None),
    month: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Profit & loss: revenue less expenses over the requested period."""
    try:
        data = await svc.income_statement(
            db, current_user.organization_id, year=year, month=month
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        )
    return IncomeStatementResponse(**data)


@router.get("/balance-sheet", response_model=BalanceSheetResponse)
async def get_balance_sheet(
    year: int | None = Query(default=None),
    month: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Assets, liabilities and equity as of the requested cutoff date."""
    try:
        data = await svc.balance_sheet(
            db, current_user.organization_id, year=year, month=month
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        )
    return BalanceSheetResponse(**data)


@router.get("/cash-flow-statement", response_model=CashFlowStatementResponse)
async def get_cash_flow_statement(
    year: int | None = Query(default=None),
    month: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Direct-method cash flows (operating/investing/financing) over a period."""
    try:
        data = await svc.cash_flow_statement(
            db, current_user.organization_id, year=year, month=month
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        )
    return CashFlowStatementResponse(**data)
