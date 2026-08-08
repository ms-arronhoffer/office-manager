"""Procurement control tests: competitive bidding and the three-way match."""

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.models.organization import Organization
from app.models.procurement import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequisition,
    RequisitionLine,
    VendorQuote,
)
from app.models.vendor_bill import VendorBill, VendorBillLine
from app.services import procurement_service
from app.services.procurement_service import ProcurementError


# ─── Pure helpers ────────────────────────────────────────────────────────────

def test_line_amount_multiplies_and_rounds():
    assert procurement_service.line_amount(3, "10.005") == Decimal("30.02")
    assert procurement_service.line_amount(0, "10") == Decimal("0.00")


def _requisition(total: str, quotes=()) -> PurchaseRequisition:
    org_id = uuid.uuid4()
    req = PurchaseRequisition(
        id=uuid.uuid4(),
        organization_id=org_id,
        title="Rooftop unit replacement",
        status="approved",
        estimated_total=Decimal(total),
    )
    req.lines = [
        RequisitionLine(
            line_number=1,
            description="Unit",
            quantity=Decimal("1"),
            unit_price=Decimal(total),
            amount=Decimal(total),
        )
    ]
    req.quotes = list(quotes)
    return req


def _quote(amount: str, selected=False, reason=None) -> VendorQuote:
    return VendorQuote(
        id=uuid.uuid4(),
        vendor_id=uuid.uuid4(),
        amount=Decimal(amount),
        is_selected=selected,
        selection_reason=reason,
    )


class _StubSession:
    """Minimal stand-in returning a fixed organization for policy lookups."""

    def __init__(self, org):
        self._org = org

    async def get(self, _model, _pk):
        return self._org


def _org(bid_threshold="5000", required_bids=3) -> Organization:
    return Organization(
        id=uuid.uuid4(),
        name="Test Org",
        slug=f"test-{uuid.uuid4().hex[:6]}",
        procurement_bid_threshold=Decimal(bid_threshold),
        procurement_required_bids=required_bids,
    )


# ─── Competitive bidding ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_below_threshold_needs_no_quotes():
    req = _requisition("1200")
    await procurement_service.assert_bids_sufficient(_StubSession(_org()), req)


@pytest.mark.asyncio
async def test_above_threshold_requires_minimum_quote_count():
    req = _requisition("9000", quotes=[_quote("9000"), _quote("9500")])
    with pytest.raises(ProcurementError, match="competing quotes"):
        await procurement_service.assert_bids_sufficient(_StubSession(_org()), req)


@pytest.mark.asyncio
async def test_above_threshold_requires_a_selected_winner():
    req = _requisition(
        "9000", quotes=[_quote("9000"), _quote("9500"), _quote("10000")]
    )
    with pytest.raises(ProcurementError, match="Select the winning vendor quote"):
        await procurement_service.assert_bids_sufficient(_StubSession(_org()), req)


@pytest.mark.asyncio
async def test_non_lowest_winner_requires_written_justification():
    req = _requisition(
        "9000",
        quotes=[_quote("9000"), _quote("9500", selected=True), _quote("10000")],
    )
    with pytest.raises(ProcurementError, match="selection reason is required"):
        await procurement_service.assert_bids_sufficient(_StubSession(_org()), req)


@pytest.mark.asyncio
async def test_non_lowest_winner_passes_with_justification():
    req = _requisition(
        "9000",
        quotes=[
            _quote("9000"),
            _quote("9500", selected=True, reason="Only bidder certified for this unit"),
            _quote("10000"),
        ],
    )
    await procurement_service.assert_bids_sufficient(_StubSession(_org()), req)


@pytest.mark.asyncio
async def test_only_one_quote_may_be_selected():
    req = _requisition(
        "9000",
        quotes=[_quote("9000", selected=True), _quote("9500", selected=True)],
    )
    with pytest.raises(ProcurementError, match="Only one vendor quote"):
        await procurement_service.assert_bids_sufficient(_StubSession(_org()), req)


# ─── Receipt status ──────────────────────────────────────────────────────────

def _order(quantity="10", received="0", total="1000") -> PurchaseOrder:
    order = PurchaseOrder(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        vendor_id=uuid.uuid4(),
        order_date=date(2026, 1, 1),
        status="issued",
        total_amount=Decimal(total),
        match_tolerance_percent=Decimal("5"),
    )
    order.lines = [
        PurchaseOrderLine(
            line_number=1,
            description="Widget",
            quantity=Decimal(quantity),
            unit_price=Decimal("100"),
            amount=Decimal(total),
            quantity_received=Decimal(received),
        )
    ]
    return order


def test_status_tracks_partial_and_full_receipt():
    assert procurement_service.recompute_status(_order(received="0")) == "issued"
    assert procurement_service.recompute_status(_order(received="4")) == "partially_received"
    assert procurement_service.recompute_status(_order(received="10")) == "received"


def test_closed_order_status_is_not_recomputed():
    order = _order(received="10")
    order.status = "closed"
    assert procurement_service.recompute_status(order) == "closed"


# ─── Three-way match ─────────────────────────────────────────────────────────

class _OrderSession:
    """Returns a single purchase order for the match lookup."""

    def __init__(self, order):
        self._order = order

    async def execute(self, _stmt):
        order = self._order

        class _Result:
            def scalar_one_or_none(self):
                return order

        return _Result()


def _bill(order, amount="1000", vendor_id=None) -> VendorBill:
    bill = VendorBill(
        id=uuid.uuid4(),
        organization_id=order.organization_id,
        vendor_id=vendor_id or order.vendor_id,
        bill_date=date(2026, 2, 1),
        status="draft",
        purchase_order_id=order.id,
    )
    bill.lines = [
        VendorBillLine(account_id=uuid.uuid4(), line_number=1, amount=Decimal(amount))
    ]
    return bill


@pytest.mark.asyncio
async def test_bill_without_purchase_order_is_allowed():
    bill = VendorBill(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        vendor_id=uuid.uuid4(),
        bill_date=date(2026, 2, 1),
        status="draft",
    )
    bill.lines = []
    await procurement_service.assert_bill_matches_order(_OrderSession(None), bill)


@pytest.mark.asyncio
async def test_bill_blocked_when_nothing_received():
    order = _order(received="0")
    with pytest.raises(ProcurementError, match="received"):
        await procurement_service.assert_bill_matches_order(
            _OrderSession(order), _bill(order)
        )


@pytest.mark.asyncio
async def test_bill_blocked_when_vendor_differs_from_order():
    order = _order(received="10")
    bill = _bill(order, vendor_id=uuid.uuid4())
    with pytest.raises(ProcurementError, match="vendor"):
        await procurement_service.assert_bill_matches_order(_OrderSession(order), bill)


@pytest.mark.asyncio
async def test_bill_blocked_when_over_tolerance():
    order = _order(received="10", total="1000")
    # 5% tolerance allows 1050; 1200 must fail.
    with pytest.raises(ProcurementError, match="exceeds the purchase order total"):
        await procurement_service.assert_bill_matches_order(
            _OrderSession(order), _bill(order, amount="1200")
        )


@pytest.mark.asyncio
async def test_bill_within_tolerance_passes():
    order = _order(received="10", total="1000")
    await procurement_service.assert_bill_matches_order(
        _OrderSession(order), _bill(order, amount="1040")
    )


@pytest.mark.asyncio
async def test_bill_blocked_when_order_cancelled():
    order = _order(received="10")
    order.status = "cancelled"
    with pytest.raises(ProcurementError, match="cancelled"):
        await procurement_service.assert_bill_matches_order(
            _OrderSession(order), _bill(order)
        )
