"""Procurement rules: competitive bidding and the three-way match.

Two controls live here, both of which an auditor will ask to see:

* **Competitive bidding** — once a requisition reaches the organization's bid
  threshold it cannot become a purchase order until the required number of
  competing quotes exist, one is explicitly selected, and a non-cheapest
  selection carries a written justification.
* **Three-way match** — a vendor bill that references a purchase order must
  agree with both the order (price) and the receipts (quantity) before it is
  allowed to post to the general ledger.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.organization import Organization
from app.models.procurement import (
    PO_OPEN_STATUSES,
    PurchaseOrder,
    PurchaseRequisition,
)

TWO = Decimal("0.01")


class ProcurementError(ValueError):
    """Raised for procurement rule violations."""


def q(value) -> Decimal:
    """Round to currency precision."""
    return Decimal(str(value or 0)).quantize(TWO, rounding=ROUND_HALF_UP)


def line_amount(quantity, unit_price) -> Decimal:
    """Extended amount for a requisition/order line."""
    return q(Decimal(str(quantity or 0)) * Decimal(str(unit_price or 0)))


async def get_bid_policy(
    db: AsyncSession, organization_id: uuid.UUID | None
) -> tuple[Decimal, int]:
    """Return ``(bid_threshold, required_bids)`` for the organization."""
    if organization_id is None:
        return Decimal("0"), 0
    org = await db.get(Organization, organization_id)
    if org is None:
        return Decimal("0"), 0
    return (
        Decimal(str(org.procurement_bid_threshold or 0)),
        int(org.procurement_required_bids or 0),
    )


async def assert_bids_sufficient(
    db: AsyncSession, requisition: PurchaseRequisition
) -> None:
    """Enforce competitive bidding before a requisition can be ordered."""
    threshold, required = await get_bid_policy(db, requisition.organization_id)
    total = q(requisition.estimated_total)
    quotes = list(requisition.quotes or [])
    selected = [quote for quote in quotes if quote.is_selected]

    if len(selected) > 1:
        raise ProcurementError("Only one vendor quote may be selected.")

    if total >= threshold and required > 0:
        if len(quotes) < required:
            raise ProcurementError(
                f"This requisition totals {total} and requires at least {required} "
                f"competing quotes; only {len(quotes)} recorded."
            )
        if not selected:
            raise ProcurementError(
                "Select the winning vendor quote before issuing a purchase order."
            )

    if selected:
        winner = selected[0]
        cheapest = min(quotes, key=lambda quote: q(quote.amount))
        if q(winner.amount) > q(cheapest.amount) and not (
            winner.selection_reason or ""
        ).strip():
            raise ProcurementError(
                "The selected quote is not the lowest bid, so a written selection "
                "reason is required."
            )


def received_quantity(order: PurchaseOrder) -> Decimal:
    """Total quantity confirmed received across all of an order's lines."""
    return q(sum((q(line.quantity_received) for line in order.lines), Decimal("0")))


def ordered_quantity(order: PurchaseOrder) -> Decimal:
    """Total quantity ordered across all of an order's lines."""
    return q(sum((q(line.quantity) for line in order.lines), Decimal("0")))


def recompute_status(order: PurchaseOrder) -> str:
    """Derive the order's receipt status from its line receipts."""
    if order.status in ("cancelled", "closed"):
        return order.status
    ordered = ordered_quantity(order)
    received = received_quantity(order)
    if received <= 0:
        return "issued"
    if received >= ordered:
        return "received"
    return "partially_received"


async def assert_bill_matches_order(db: AsyncSession, bill) -> None:
    """Three-way match guard, called just before a vendor bill posts.

    Bills without a purchase order are allowed through: not all spend is
    ordered in advance. When an order is referenced, the invoice must agree
    with what was ordered and what was received.
    """
    if getattr(bill, "purchase_order_id", None) is None:
        return

    order = (
        await db.execute(
            select(PurchaseOrder)
            .where(PurchaseOrder.id == bill.purchase_order_id)
            .options(selectinload(PurchaseOrder.lines))
        )
    ).scalar_one_or_none()
    if order is None:
        raise ProcurementError("The referenced purchase order no longer exists.")
    if order.organization_id != bill.organization_id:
        raise ProcurementError("The referenced purchase order belongs to another organization.")
    if order.vendor_id != bill.vendor_id:
        raise ProcurementError(
            "This bill's vendor does not match the vendor on the purchase order."
        )
    if order.status not in PO_OPEN_STATUSES:
        raise ProcurementError(
            f"Purchase order is {order.status} and cannot be invoiced against."
        )

    if received_quantity(order) <= 0:
        raise ProcurementError(
            "Nothing has been recorded as received against this purchase order yet."
        )

    bill_total = q(sum((q(line.amount) for line in bill.lines), Decimal("0")))
    tolerance = Decimal(str(order.match_tolerance_percent or 0)) / Decimal("100")
    ceiling = q(q(order.total_amount) * (Decimal("1") + tolerance))
    if bill_total > ceiling:
        raise ProcurementError(
            f"Bill total {bill_total} exceeds the purchase order total "
            f"{q(order.total_amount)} beyond the allowed tolerance."
        )
