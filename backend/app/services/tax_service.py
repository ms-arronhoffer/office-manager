"""Tax / 1099 reporting service (Phase 1.3).

Aggregates the existing accounts-payable payment history into 1099 totals so
finance staff can prepare 1099-NEC / 1099-MISC filings without a parallel
ledger. Nothing here posts to the GL — it is a read/report layer over the
``vendor_payments`` recorded by the AP module.

Reportability and box assignment are resolved per payment with a simple
override/inherit rule:

  - ``VendorPayment.is_reportable`` overrides the vendor's ``is_1099_vendor``
    flag when set (NULL => inherit).
  - ``VendorPayment.tax_box`` overrides the vendor's ``default_tax_box`` when
    set (NULL => inherit, falling back to ``nec_1``).

A payment only contributes to a form if the payment date falls in the requested
tax year and the vendor/payment resolves to reportable. Corporation tax
classifications (``c_corp`` / ``s_corp``) are excluded by default because
corporate payments are generally exempt from 1099 reporting.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vendor import Vendor
from app.models.vendor_bill import VendorPayment

TWO = Decimal("0.01")

# Supported 1099 boxes: key -> (form, box number, human label).
TAX_BOXES: dict[str, tuple[str, str, str]] = {
    "nec_1": ("1099-NEC", "1", "Nonemployee compensation"),
    "misc_1": ("1099-MISC", "1", "Rents"),
    "misc_3": ("1099-MISC", "3", "Other income"),
    "misc_6": ("1099-MISC", "6", "Medical and health care payments"),
}

DEFAULT_BOX = "nec_1"

# Minimum aggregate payment amount (per form) before a 1099 must be filed.
FORM_THRESHOLDS: dict[str, Decimal] = {
    "1099-NEC": Decimal("600.00"),
    "1099-MISC": Decimal("600.00"),
}

# Tax classifications that are exempt from 1099 reporting by default.
EXEMPT_CLASSIFICATIONS = {"c_corp", "s_corp"}


class TaxError(ValueError):
    """Raised for tax-reporting rule violations."""


def _q(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(TWO, rounding=ROUND_HALF_UP)


def normalize_box(box: str | None) -> str:
    """Return a known box key, falling back to the default (``nec_1``)."""
    if box and box in TAX_BOXES:
        return box
    return DEFAULT_BOX


def form_for_box(box: str | None) -> str:
    """Return the IRS form (``1099-NEC`` / ``1099-MISC``) for a box key."""
    return TAX_BOXES[normalize_box(box)][0]


def payment_is_reportable(payment: VendorPayment, vendor: Vendor) -> bool:
    """Resolve whether a payment counts toward 1099 totals.

    Per-payment ``is_reportable`` overrides the vendor flag; exempt corporate
    classifications are never reportable unless explicitly forced on the payment.
    """
    if payment.is_reportable is not None:
        return bool(payment.is_reportable)
    if (vendor.tax_classification or "").lower() in EXEMPT_CLASSIFICATIONS:
        return False
    return bool(vendor.is_1099_vendor)


def payment_box(payment: VendorPayment, vendor: Vendor) -> str:
    """Resolve the 1099 box for a payment (override → vendor default → NEC)."""
    return normalize_box(payment.tax_box or vendor.default_tax_box)


def _year_bounds(year: int) -> tuple[date, date]:
    return date(year, 1, 1), date(year, 12, 31)


async def aggregate_1099(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    year: int,
    *,
    form: str | None = None,
    include_below_threshold: bool = True,
) -> list[dict]:
    """Aggregate reportable vendor payments into per-vendor 1099 summaries.

    Returns one entry per (vendor) that has at least one reportable payment in
    the year, with per-box totals and a ``meets_threshold`` flag. When ``form``
    is given (``1099-NEC`` / ``1099-MISC``) only boxes for that form are
    included. When ``include_below_threshold`` is False, vendors whose total for
    the (filtered) form is under the IRS threshold are omitted.
    """
    start, end = _year_bounds(year)

    # Explicit join through the bill to the vendor.
    from app.models.vendor_bill import VendorBill

    stmt = (
        select(VendorPayment, Vendor)
        .join(VendorBill, VendorPayment.bill_id == VendorBill.id)
        .join(Vendor, VendorBill.vendor_id == Vendor.id)
        .where(
            VendorPayment.organization_id == organization_id,
            VendorPayment.payment_date >= start,
            VendorPayment.payment_date <= end,
        )
    )
    result = await db.execute(stmt)

    # vendor_id -> aggregate accumulator
    agg: dict[uuid.UUID, dict] = {}
    for payment, vendor in result.all():
        if not payment_is_reportable(payment, vendor):
            continue
        box = payment_box(payment, vendor)
        box_form = TAX_BOXES[box][0]
        if form and box_form != form:
            continue
        amount = _q(payment.amount)
        if amount <= 0:
            continue

        entry = agg.get(vendor.id)
        if entry is None:
            entry = {
                "vendor_id": vendor.id,
                "vendor_name": vendor.company_name,
                "legal_name": vendor.legal_name or vendor.company_name,
                "tax_id": vendor.tax_id,
                "tax_id_type": vendor.tax_id_type,
                "tax_classification": vendor.tax_classification,
                "boxes": {},
                "total": Decimal("0.00"),
                "payment_count": 0,
            }
            agg[vendor.id] = entry
        entry["boxes"][box] = _q(entry["boxes"].get(box, Decimal("0.00")) + amount)
        entry["total"] = _q(entry["total"] + amount)
        entry["payment_count"] += 1

    summaries: list[dict] = []
    for entry in agg.values():
        # A vendor meets the threshold if any single form's total reaches it.
        form_totals: dict[str, Decimal] = {}
        for box, amt in entry["boxes"].items():
            f = TAX_BOXES[box][0]
            form_totals[f] = _q(form_totals.get(f, Decimal("0.00")) + amt)
        meets = any(
            total >= FORM_THRESHOLDS.get(f, Decimal("600.00"))
            for f, total in form_totals.items()
        )
        entry["form_totals"] = form_totals
        entry["meets_threshold"] = meets
        if not include_below_threshold and not meets:
            continue
        summaries.append(entry)

    summaries.sort(key=lambda e: e["total"], reverse=True)
    return summaries


async def vendor_1099_detail(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    vendor_id: uuid.UUID,
    year: int,
) -> dict | None:
    """Return a single vendor's 1099 detail with its reportable payments."""
    from app.models.vendor_bill import VendorBill

    start, end = _year_bounds(year)
    vendor = (
        await db.execute(
            select(Vendor).where(
                Vendor.id == vendor_id,
                Vendor.organization_id == organization_id,
            )
        )
    ).scalar_one_or_none()
    if vendor is None:
        return None

    stmt = (
        select(VendorPayment)
        .join(VendorBill, VendorPayment.bill_id == VendorBill.id)
        .where(
            VendorBill.vendor_id == vendor_id,
            VendorPayment.organization_id == organization_id,
            VendorPayment.payment_date >= start,
            VendorPayment.payment_date <= end,
        )
        .order_by(VendorPayment.payment_date)
    )
    payments = (await db.execute(stmt)).scalars().all()

    boxes: dict[str, Decimal] = {}
    detail_payments: list[dict] = []
    total = Decimal("0.00")
    for payment in payments:
        reportable = payment_is_reportable(payment, vendor)
        box = payment_box(payment, vendor)
        amount = _q(payment.amount)
        if reportable and amount > 0:
            boxes[box] = _q(boxes.get(box, Decimal("0.00")) + amount)
            total = _q(total + amount)
        detail_payments.append(
            {
                "payment_id": payment.id,
                "payment_date": payment.payment_date,
                "amount": amount,
                "reportable": reportable,
                "box": box if reportable else None,
                "reference": payment.reference,
            }
        )

    return {
        "vendor_id": vendor.id,
        "vendor_name": vendor.company_name,
        "legal_name": vendor.legal_name or vendor.company_name,
        "tax_id": vendor.tax_id,
        "tax_id_type": vendor.tax_id_type,
        "tax_classification": vendor.tax_classification,
        "year": year,
        "boxes": boxes,
        "total": total,
        "payments": detail_payments,
    }
