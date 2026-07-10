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
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_feature, require_role
from app.database import get_db
from app.models.organization import Organization
from app.models.site_settings import SiteSettings
from app.models.user import User
from app.services import accounting_audit_service as audit_svc
from app.services import financials_service as svc
from app.utils.pdf_generator import generate_statement_pdf

router = APIRouter()

# Finance staff only.
FinanceUser = require_role("admin", "accountant")
# PDF export additionally requires the 'pdf_export' plan entitlement.
FinancePdfUser = require_feature("pdf_export")


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


class AuditCheck(BaseModel):
    key: str
    description: str
    category: str
    status: str
    detail: str
    findings: list[str]
    finding_count: int


class AuditControlAccount(BaseModel):
    code: str
    name: str
    balance: Decimal
    balance_side: str


class AuditStatementSummary(BaseModel):
    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal
    net_income: Decimal
    ending_cash: Decimal


class AuditReportResponse(BaseModel):
    attested: bool
    entry_count: int
    total_debits: Decimal
    total_credits: Decimal
    checks_total: int
    checks_passed: int
    checks_failed: int
    control_accounts: list[AuditControlAccount]
    checks: list[AuditCheck]
    statement_summary: AuditStatementSummary


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


def _period_label(start_date: date | None, end_date: date | None) -> str:
    if start_date and end_date:
        if start_date.year == end_date.year and start_date.month == end_date.month:
            return f"For the month ended {end_date.strftime('%B %d, %Y')}"
        return f"For the period {start_date.strftime('%B %d, %Y')} – {end_date.strftime('%B %d, %Y')}"
    if end_date:
        return f"As of {end_date.strftime('%B %d, %Y')}"
    return "Since inception"


async def _org_name(db: AsyncSession, current_user: User) -> str:
    if current_user.organization_id is None:
        return "Financial Statements"
    result = await db.execute(
        select(Organization).where(Organization.id == current_user.organization_id)
    )
    org = result.scalar_one_or_none()
    return org.name if org else "Financial Statements"


async def _report_header(db: AsyncSession, current_user: User) -> tuple[str, str]:
    """Return the (company name, contact line) used to head generated reports."""
    org_name = await _org_name(db, current_user)
    if current_user.organization_id is None:
        return org_name, ""
    result = await db.execute(
        select(SiteSettings).where(SiteSettings.organization_id == current_user.organization_id)
    )
    settings = result.scalar_one_or_none()
    if not settings:
        return org_name, ""
    company_name = settings.company_name or org_name
    contact_parts = [
        part
        for part in (settings.company_address, settings.company_phone, settings.company_email)
        if part
    ]
    return company_name, " · ".join(contact_parts)


def _lines_to_rows(lines: list[StatementLine]) -> list[tuple[str, str, Decimal]]:
    return [(l.code, l.name, l.amount) for l in lines]


@router.get("/income-statement/pdf")
async def get_income_statement_pdf(
    year: int | None = Query(default=None),
    month: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
    _pdf: User = Depends(FinancePdfUser),
):
    """Executive-ready PDF of the income statement for the requested period."""
    try:
        data = await svc.income_statement(
            db, current_user.organization_id, year=year, month=month
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        )
    resp = IncomeStatementResponse(**data)
    company_name, company_contact = await _report_header(db, current_user)
    buffer = generate_statement_pdf(
        company_name=company_name,
        company_contact=company_contact,
        statement_title="Income Statement",
        period_label=_period_label(resp.start_date, resp.end_date),
        sections=[
            {
                "title": "Revenue",
                "rows": _lines_to_rows(resp.revenue),
                "total_label": "Total revenue",
                "total": resp.total_revenue,
            },
            {
                "title": "Expenses",
                "rows": _lines_to_rows(resp.expenses),
                "total_label": "Total expenses",
                "total": resp.total_expenses,
            },
        ],
        summary_lines=[("Net income", resp.net_income)],
    )
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="income_statement.pdf"'},
    )


@router.get("/balance-sheet/pdf")
async def get_balance_sheet_pdf(
    year: int | None = Query(default=None),
    month: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
    _pdf: User = Depends(FinancePdfUser),
):
    """Executive-ready PDF of the balance sheet as of the requested cutoff."""
    try:
        data = await svc.balance_sheet(
            db, current_user.organization_id, year=year, month=month
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        )
    resp = BalanceSheetResponse(**data)
    company_name, company_contact = await _report_header(db, current_user)
    buffer = generate_statement_pdf(
        company_name=company_name,
        company_contact=company_contact,
        statement_title="Balance Sheet",
        period_label=_period_label(None, resp.as_of_date),
        sections=[
            {
                "title": "Assets",
                "rows": _lines_to_rows(resp.assets),
                "total_label": "Total assets",
                "total": resp.total_assets,
            },
            {
                "title": "Liabilities",
                "rows": _lines_to_rows(resp.liabilities),
                "total_label": "Total liabilities",
                "total": resp.total_liabilities,
            },
            {
                "title": "Equity",
                "rows": _lines_to_rows(resp.equity),
                "total_label": "Total equity",
                "total": resp.total_equity,
            },
        ],
        summary_lines=[
            ("Total liabilities & equity", resp.liabilities_and_equity),
            ("Balanced", "Yes" if resp.balanced else "No — out of balance"),
        ],
    )
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="balance_sheet.pdf"'},
    )


@router.get("/cash-flow-statement/pdf")
async def get_cash_flow_statement_pdf(
    year: int | None = Query(default=None),
    month: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
    _pdf: User = Depends(FinancePdfUser),
):
    """Executive-ready PDF of the cash flow statement for the requested period."""
    try:
        data = await svc.cash_flow_statement(
            db, current_user.organization_id, year=year, month=month
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        )
    resp = CashFlowStatementResponse(**data)
    company_name, company_contact = await _report_header(db, current_user)
    buffer = generate_statement_pdf(
        company_name=company_name,
        company_contact=company_contact,
        statement_title="Statement of Cash Flows",
        period_label=_period_label(resp.start_date, resp.end_date),
        sections=[
            {
                "title": "Operating activities",
                "rows": _lines_to_rows(resp.operating.lines),
                "total_label": "Net cash from operating",
                "total": resp.operating.total,
            },
            {
                "title": "Investing activities",
                "rows": _lines_to_rows(resp.investing.lines),
                "total_label": "Net cash from investing",
                "total": resp.investing.total,
            },
            {
                "title": "Financing activities",
                "rows": _lines_to_rows(resp.financing.lines),
                "total_label": "Net cash from financing",
                "total": resp.financing.total,
            },
        ],
        summary_lines=[
            ("Beginning cash", resp.beginning_cash),
            ("Net change in cash", resp.net_change_in_cash),
            ("Ending cash", resp.ending_cash),
        ],
    )
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="cash_flow_statement.pdf"'},
    )


@router.get("/audit-report", response_model=AuditReportResponse)
async def get_audit_report(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Run the built-in accounting auditor and return an attestation report.

    Independently re-derives double-entry, line, scope, period, audit-trail,
    statement cross-tie and control-account invariants over the whole ledger.
    ``attested`` is true only when every check passes.
    """
    data = await audit_svc.run_audit(db, current_user.organization_id)
    return AuditReportResponse(**data)

