"""Tax / 1099 API router (Phase 1.3) — `/api/v1/tax`.

Read-only 1099 reporting over the accounts-payable payment history. Finance
staff (``admin`` / ``accountant``) can review per-vendor 1099 totals for a tax
year, drill into an individual vendor's reportable payments, and export a CSV
suitable for preparing 1099-NEC / 1099-MISC filings.

No GL postings happen here; this is a reporting layer over ``vendor_payments``.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.database import get_db
from app.models.user import User
from app.services import tax_service as svc

router = APIRouter()

# Finance staff only.
FinanceUser = require_role("admin", "accountant")


# ─── Schemas ────────────────────────────────────────────────────────────────

class BoxAmount(BaseModel):
    box: str
    form: str
    label: str
    amount: Decimal


class Vendor1099Summary(BaseModel):
    vendor_id: uuid.UUID
    vendor_name: str
    legal_name: str
    tax_id: str | None
    tax_id_type: str | None
    tax_classification: str | None
    total: Decimal
    payment_count: int
    meets_threshold: bool
    boxes: list[BoxAmount]


class Payment1099(BaseModel):
    payment_id: uuid.UUID
    payment_date: date
    amount: Decimal
    reportable: bool
    box: str | None
    reference: str | None


class Vendor1099Detail(BaseModel):
    vendor_id: uuid.UUID
    vendor_name: str
    legal_name: str
    tax_id: str | None
    tax_id_type: str | None
    tax_classification: str | None
    year: int
    total: Decimal
    boxes: list[BoxAmount]
    payments: list[Payment1099]


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _boxes(box_totals: dict[str, Decimal]) -> list[BoxAmount]:
    out: list[BoxAmount] = []
    for box, amount in box_totals.items():
        form, number, label = svc.TAX_BOXES[box]
        out.append(BoxAmount(box=box, form=form, label=f"Box {number}: {label}", amount=amount))
    out.sort(key=lambda b: b.box)
    return out


def _validate_year(year: int) -> int:
    if year < 2000 or year > date.today().year + 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Year must be a valid tax year.",
        )
    return year


def _validate_form(form: str | None) -> str | None:
    if form is None:
        return None
    normalized = form.upper()
    if normalized not in {"1099-NEC", "1099-MISC"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="form must be one of: 1099-NEC, 1099-MISC.",
        )
    return normalized


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/1099", response_model=list[Vendor1099Summary])
async def list_1099_summary(
    year: int = Query(..., description="Tax year, e.g. 2025"),
    form: str | None = Query(default=None, description="1099-NEC or 1099-MISC"),
    only_reportable: bool = Query(
        default=False,
        description="Only include vendors that meet the filing threshold.",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Per-vendor 1099 totals for a tax year."""
    _validate_year(year)
    form = _validate_form(form)
    summaries = await svc.aggregate_1099(
        db,
        current_user.organization_id,
        year,
        form=form,
        include_below_threshold=not only_reportable,
    )
    return [
        Vendor1099Summary(
            vendor_id=s["vendor_id"],
            vendor_name=s["vendor_name"],
            legal_name=s["legal_name"],
            tax_id=s["tax_id"],
            tax_id_type=s["tax_id_type"],
            tax_classification=s["tax_classification"],
            total=s["total"],
            payment_count=s["payment_count"],
            meets_threshold=s["meets_threshold"],
            boxes=_boxes(s["boxes"]),
        )
        for s in summaries
    ]


@router.get("/1099/export")
async def export_1099_csv(
    year: int = Query(..., description="Tax year, e.g. 2025"),
    form: str | None = Query(default=None, description="1099-NEC or 1099-MISC"),
    only_reportable: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """Export 1099 totals as a CSV suitable for preparing filings."""
    _validate_year(year)
    form = _validate_form(form)
    summaries = await svc.aggregate_1099(
        db,
        current_user.organization_id,
        year,
        form=form,
        include_below_threshold=not only_reportable,
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "tax_year",
            "vendor_name",
            "legal_name",
            "tax_id",
            "tax_id_type",
            "tax_classification",
            "form",
            "box",
            "box_label",
            "amount",
            "meets_threshold",
        ]
    )
    for s in summaries:
        for box, amount in sorted(s["boxes"].items()):
            box_form, number, label = svc.TAX_BOXES[box]
            writer.writerow(
                [
                    year,
                    s["vendor_name"],
                    s["legal_name"],
                    s["tax_id"] or "",
                    s["tax_id_type"] or "",
                    s["tax_classification"] or "",
                    box_form,
                    number,
                    label,
                    f"{amount:.2f}",
                    "yes" if s["meets_threshold"] else "no",
                ]
            )

    buffer.seek(0)
    filename = f"1099_{year}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/1099/{vendor_id}", response_model=Vendor1099Detail)
async def get_1099_detail(
    vendor_id: uuid.UUID,
    year: int = Query(..., description="Tax year, e.g. 2025"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(FinanceUser),
):
    """A single vendor's 1099 detail with its reportable payments."""
    _validate_year(year)
    detail = await svc.vendor_1099_detail(
        db, current_user.organization_id, vendor_id, year
    )
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Vendor not found"
        )
    return Vendor1099Detail(
        vendor_id=detail["vendor_id"],
        vendor_name=detail["vendor_name"],
        legal_name=detail["legal_name"],
        tax_id=detail["tax_id"],
        tax_id_type=detail["tax_id_type"],
        tax_classification=detail["tax_classification"],
        year=detail["year"],
        total=detail["total"],
        boxes=_boxes(detail["boxes"]),
        payments=[Payment1099(**p) for p in detail["payments"]],
    )
