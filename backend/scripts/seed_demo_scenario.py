"""Seed a bid-ready demonstration scenario.

An empty product demos badly. Reviewers see zero-value dashboards and blank
tables and conclude the capability is not there, regardless of what the code
supports. This script populates one organization with a coherent story that
exercises each control end to end, so a scripted walkthrough can show:

  * a purchase requisition with three competing bids, approved by a second
    person, issued as a purchase order, received, then invoiced and matched;
  * a vendor bill that cannot post until someone other than its preparer
    approves it;
  * leases whose notice deadlines are close enough to appear in the work queue,
    including one already overdue;
  * an office transition with owned, dated and dependent checklist tasks;
  * open maintenance work at mixed priorities.

Run from the backend directory:

    python -m scripts.seed_demo_scenario --org-slug acme --reset

``--reset`` removes previously seeded demo rows for that organization first, so
the script can be re-run before a demo without accumulating duplicates.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.password import hash_password
from app.database import async_session
from app.models import (  # noqa: F401 - importing registers every model
    Lease,
    LeaseOption,
    LeaseRenewal,
    MaintenanceTicket,
    Office,
    Organization,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderReceipt,
    PurchaseRequisition,
    ReceiptLine,
    RequisitionLine,
    TicketCategory,
    User,
    Vendor,
    VendorBill,
    VendorBillLine,
    VendorQuote,
)
from app.models.transition import OfficeTransition, TransitionChecklistItem
from app.services import gl_service

# Marker written into free-text fields so --reset can find what we created.
DEMO_TAG = "[demo-scenario]"

TODAY = date.today()


async def _get_org(db: AsyncSession, slug: str) -> Organization:
    org = (
        await db.execute(select(Organization).where(Organization.slug == slug))
    ).scalar_one_or_none()
    if org is None:
        sys.exit(f"No organization with slug '{slug}'. Create it first.")
    return org


async def _ensure_user(
    db: AsyncSession, org: Organization, email: str, name: str, role: str
) -> User:
    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if user:
        return user
    user = User(
        email=email,
        display_name=name,
        password_hash=hash_password("DemoPass123!"),
        auth_provider="internal",
        role=role,
        is_active=True,
        organization_id=org.id,
    )
    db.add(user)
    await db.flush()
    return user


async def _reset(db: AsyncSession, org: Organization) -> None:
    """Remove rows a previous run of this script created."""
    for model, column in (
        (VendorBill, VendorBill.memo),
        (PurchaseRequisition, PurchaseRequisition.description),
        (MaintenanceTicket, MaintenanceTicket.subject),
        (OfficeTransition, OfficeTransition.notes),
    ):
        rows = (
            (
                await db.execute(
                    select(model).where(
                        model.organization_id == org.id,
                        column.ilike(f"%{DEMO_TAG}%"),
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            await db.delete(row)
    await db.commit()


async def seed(slug: str, reset: bool) -> None:
    async with async_session() as db:
        org = await _get_org(db, slug)

        if reset:
            await _reset(db, org)

        # A demo of separation of duties needs two distinct people.
        preparer = await _ensure_user(
            db, org, "demo.preparer@example.com", "Dana Preparer", "accountant"
        )
        approver = await _ensure_user(
            db, org, "demo.approver@example.com", "Alex Approver", "admin"
        )

        await gl_service.seed_default_accounts(db, org.id)
        # The default chart has no facilities expense account, so add the one the
        # scenario codes its spend to rather than guessing at an existing row.
        await gl_service.ensure_accounts(
            db, org.id, [("6300", "Repairs & Maintenance", "expense")]
        )
        accounts = await gl_service.get_account_map(db, org.id)
        expense_account = accounts["Repairs & Maintenance"]

        office = await _ensure_office(db, org)
        vendor = await _ensure_vendor(db, org)

        await _seed_lease_deadlines(db, org, office)
        requisition, order = await _seed_procurement(
            db, org, office, vendor, preparer, approver, expense_account.id
        )
        await _seed_matched_bill(db, org, vendor, order, preparer, expense_account.id)
        await _seed_unapproved_bill(db, org, vendor, preparer, expense_account.id)
        await _seed_transition(db, org, office, preparer, approver)
        await _seed_tickets(db, org, office)

        await db.commit()

        # Read the summary values before the session closes and detaches them.
        summary = (requisition.title, str(order.total_amount), str(order.po_number))

    print("Demo scenario seeded.")
    print("  Preparer: demo.preparer@example.com / DemoPass123!")
    print("  Approver: demo.approver@example.com / DemoPass123!")
    print(f"  Requisition: {summary[0]}")
    print(f"  Purchase order {summary[2]} total: {summary[1]}")


async def _ensure_office(db: AsyncSession, org: Organization) -> Office:
    office = (
        await db.execute(
            select(Office).where(
                Office.organization_id == org.id, Office.office_number == 101
            )
        )
    ).scalar_one_or_none()
    if office:
        return office
    office = Office(
        organization_id=org.id,
        office_number=101,
        region_number=1,
        location_type="Office",
        location_name="Harbor View Tower",
        is_active=True,
    )
    db.add(office)
    await db.flush()
    return office


async def _ensure_vendor(db: AsyncSession, org: Organization) -> Vendor:
    vendor = (
        await db.execute(
            select(Vendor).where(
                Vendor.organization_id == org.id,
                Vendor.name == "Bluepeak HVAC & Mechanical",
            )
        )
    ).scalar_one_or_none()
    if vendor:
        return vendor
    vendor = Vendor(
        organization_id=org.id,
        name="Bluepeak HVAC & Mechanical",
        email="service@bluepeak.example",
    )
    db.add(vendor)
    await db.flush()
    return vendor


async def _seed_lease_deadlines(
    db: AsyncSession, org: Organization, office: Office
) -> None:
    """Leases positioned so the work queue has something real to show."""
    scenarios = [
        # (name, expiration offset days, notice days) -> lands in each band.
        ("Harbor View Tower - Suite 400", 210, 120),  # notice due in ~90 days
        ("Cedar Ridge Commons - Floor 2", 100, 90),  # notice due in ~10 days
        ("Meridian Plaza - Full Floor 12", 60, 90),  # notice already overdue
    ]
    for name, exp_offset, notice_days in scenarios:
        existing = (
            await db.execute(
                select(Lease).where(
                    Lease.organization_id == org.id, Lease.lease_name == name
                )
            )
        ).scalar_one_or_none()
        if existing:
            continue
        expiration = TODAY + timedelta(days=exp_offset)
        lease = Lease(
            organization_id=org.id,
            office_id=office.id,
            lease_name=name,
            lease_expiration=expiration,
            expiration_year=expiration.year,
            notice_period_days=notice_days,
            lease_notice_date=expiration - timedelta(days=notice_days),
            status="active",
        )
        db.add(lease)
        await db.flush()

        # One lease also carries an option whose window is closing, which is a
        # different deadline type and shows the option-exercise path.
        if name.startswith("Harbor"):
            db.add(
                LeaseOption(
                    lease_id=lease.id,
                    option_type="renewal",
                    exercise_window_start=TODAY - timedelta(days=30),
                    exercise_window_end=TODAY + timedelta(days=21),
                    notice_required_days=60,
                    new_term_months=60,
                    new_rent_amount=Decimal("5200.00"),
                    status="open",
                )
            )


async def _seed_procurement(
    db: AsyncSession,
    org: Organization,
    office: Office,
    vendor: Vendor,
    preparer: User,
    approver: User,
    account_id: uuid.UUID,
) -> tuple[PurchaseRequisition, PurchaseOrder]:
    """A fully evidenced buy: three bids, an approval, an order, a receipt."""
    requisition = PurchaseRequisition(
        organization_id=org.id,
        requisition_number="REQ-1001",
        title="Replace rooftop HVAC unit RTU-3",
        description=f"{DEMO_TAG} Unit failed compressor; replacement required.",
        office_id=office.id,
        category="HVAC",
        needed_by=TODAY + timedelta(days=30),
        status="approved",
        estimated_total=Decimal("18500.00"),
        requested_by_id=preparer.id,
        prepared_by_id=preparer.id,
        submitted_by_id=preparer.id,
        submitted_at=datetime.now(timezone.utc) - timedelta(days=6),
        approval_status="approved",
        approved_by_id=approver.id,
        approved_at=datetime.now(timezone.utc) - timedelta(days=5),
    )
    requisition.lines.append(
        RequisitionLine(
            line_number=1,
            description="Rooftop packaged unit, 15 ton, installed",
            quantity=Decimal("1"),
            unit_price=Decimal("18500.00"),
            amount=Decimal("18500.00"),
            account_id=account_id,
        )
    )

    # Competing bids, with the winner deliberately not the cheapest so the
    # written justification requirement is visible in the demo.
    other_vendors = await _ensure_bid_vendors(db, org)
    requisition.quotes.append(
        VendorQuote(
            vendor_id=other_vendors[0].id,
            amount=Decimal("17250.00"),
            quote_date=TODAY - timedelta(days=10),
            reference="Q-8841",
        )
    )
    requisition.quotes.append(
        VendorQuote(
            vendor_id=other_vendors[1].id,
            amount=Decimal("19900.00"),
            quote_date=TODAY - timedelta(days=9),
            reference="Q-3320",
        )
    )
    requisition.quotes.append(
        VendorQuote(
            vendor_id=vendor.id,
            amount=Decimal("18500.00"),
            quote_date=TODAY - timedelta(days=8),
            reference="Q-5567",
            is_selected=True,
            selection_reason=(
                "Only bidder factory-certified for this unit and able to meet the "
                "30-day outage window."
            ),
            selected_by_id=preparer.id,
            selected_at=datetime.now(timezone.utc) - timedelta(days=7),
        )
    )
    db.add(requisition)
    await db.flush()

    order = PurchaseOrder(
        organization_id=org.id,
        requisition_id=requisition.id,
        vendor_id=vendor.id,
        po_number="PO-2041",
        order_date=TODAY - timedelta(days=4),
        expected_date=TODAY + timedelta(days=20),
        status="received",
        total_amount=Decimal("18500.00"),
        memo=f"{DEMO_TAG} Issued from REQ-1001.",
        issued_by_id=approver.id,
        issued_at=datetime.now(timezone.utc) - timedelta(days=4),
    )
    po_line = PurchaseOrderLine(
        line_number=1,
        description="Rooftop packaged unit, 15 ton, installed",
        quantity=Decimal("1"),
        unit_price=Decimal("18500.00"),
        amount=Decimal("18500.00"),
        quantity_received=Decimal("1"),
        account_id=account_id,
    )
    order.lines.append(po_line)
    db.add(order)
    await db.flush()

    receipt = PurchaseOrderReceipt(
        purchase_order_id=order.id,
        received_on=TODAY - timedelta(days=1),
        received_by_id=preparer.id,
        notes=f"{DEMO_TAG} Unit delivered and commissioned.",
    )
    receipt.lines.append(
        ReceiptLine(purchase_order_line_id=po_line.id, quantity=Decimal("1"))
    )
    db.add(receipt)
    requisition.status = "ordered"
    requisition.ordered_at = datetime.now(timezone.utc) - timedelta(days=4)
    await db.flush()
    return requisition, order


async def _ensure_bid_vendors(db: AsyncSession, org: Organization) -> list[Vendor]:
    names = ["Summit Mechanical Services", "Ironline Building Systems"]
    vendors: list[Vendor] = []
    for name in names:
        vendor = (
            await db.execute(
                select(Vendor).where(
                    Vendor.organization_id == org.id, Vendor.name == name
                )
            )
        ).scalar_one_or_none()
        if vendor is None:
            vendor = Vendor(organization_id=org.id, name=name)
            db.add(vendor)
            await db.flush()
        vendors.append(vendor)
    return vendors


async def _seed_matched_bill(
    db: AsyncSession,
    org: Organization,
    vendor: Vendor,
    order: PurchaseOrder,
    preparer: User,
    account_id: uuid.UUID,
) -> None:
    """A bill that references its order, ready to demonstrate the match."""
    bill = VendorBill(
        organization_id=org.id,
        vendor_id=vendor.id,
        bill_number="BP-77301",
        bill_date=TODAY,
        due_date=TODAY + timedelta(days=30),
        memo=f"{DEMO_TAG} RTU-3 replacement, against PO-2041.",
        purchase_order_id=order.id,
        status="draft",
        total_amount=Decimal("18500.00"),
        prepared_by_id=preparer.id,
        submitted_by_id=preparer.id,
        submitted_at=datetime.now(timezone.utc),
        approval_status="pending",
    )
    bill.lines.append(
        VendorBillLine(
            account_id=account_id,
            line_number=1,
            description="Rooftop packaged unit, 15 ton, installed",
            amount=Decimal("18500.00"),
        )
    )
    db.add(bill)


async def _seed_unapproved_bill(
    db: AsyncSession,
    org: Organization,
    vendor: Vendor,
    preparer: User,
    account_id: uuid.UUID,
) -> None:
    """Non-PO spend awaiting a second signature, for the approvals demo."""
    bill = VendorBill(
        organization_id=org.id,
        vendor_id=vendor.id,
        bill_number="BP-77410",
        bill_date=TODAY,
        due_date=TODAY + timedelta(days=14),
        memo=f"{DEMO_TAG} Emergency after-hours callout.",
        status="draft",
        total_amount=Decimal("2450.00"),
        prepared_by_id=preparer.id,
        submitted_by_id=preparer.id,
        submitted_at=datetime.now(timezone.utc),
        approval_status="pending",
    )
    bill.lines.append(
        VendorBillLine(
            account_id=account_id,
            line_number=1,
            description="After-hours emergency callout",
            amount=Decimal("2450.00"),
        )
    )
    db.add(bill)


async def _seed_transition(
    db: AsyncSession,
    org: Organization,
    office: Office,
    assignee: User,
    second_assignee: User,
) -> None:
    """A relocation with owned, dated and dependent tasks, one overdue."""
    transition = OfficeTransition(
        organization_id=org.id,
        office_id=office.id,
        office_number=office.office_number,
        transition_type="relocation",
        status="in_progress",
        sheet_name="Harbor View relocation",
        estimated_date=(TODAY + timedelta(days=45)).isoformat(),
        notes=f"{DEMO_TAG} Consolidating floors 3 and 4 into Meridian Plaza.",
    )
    db.add(transition)
    await db.flush()

    survey = TransitionChecklistItem(
        transition_id=transition.id,
        item_label="Complete site survey and floor plan",
        sort_order=1,
        assigned_to_id=assignee.id,
        due_date=TODAY - timedelta(days=3),  # overdue, so escalation has a target
        is_required=True,
        requires_evidence=True,
    )
    db.add(survey)
    await db.flush()

    # Deliberately dependent on the survey so the blocking rule is demonstrable.
    db.add(
        TransitionChecklistItem(
            transition_id=transition.id,
            item_label="Book movers and freight elevator",
            sort_order=2,
            assigned_to_id=second_assignee.id,
            due_date=TODAY + timedelta(days=10),
            depends_on_id=survey.id,
            is_required=True,
        )
    )
    db.add(
        TransitionChecklistItem(
            transition_id=transition.id,
            item_label="Transfer network circuits and update DNS",
            sort_order=3,
            assigned_to_id=assignee.id,
            due_date=TODAY + timedelta(days=20),
            is_required=True,
            requires_evidence=True,
        )
    )


async def _seed_tickets(db: AsyncSession, org: Organization, office: Office) -> None:
    category = (
        await db.execute(
            select(TicketCategory).where(
                TicketCategory.organization_id == org.id,
                TicketCategory.name == "HVAC",
            )
        )
    ).scalar_one_or_none()
    if category is None:
        category = TicketCategory(organization_id=org.id, name="HVAC")
        db.add(category)
        await db.flush()

    for subject, priority, status_value in (
        ("Rooftop unit short-cycling", "high", "in_progress"),
        ("Lobby thermostat unresponsive", "medium", "open"),
    ):
        db.add(
            MaintenanceTicket(
                organization_id=org.id,
                office_id=office.id,
                category_id=category.id,
                subject=f"{subject} {DEMO_TAG}",
                priority=priority,
                status=status_value,
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a demo scenario.")
    parser.add_argument("--org-slug", required=True, help="Target organization slug.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Remove rows created by a previous run before seeding.",
    )
    args = parser.parse_args()
    asyncio.run(seed(args.org_slug, args.reset))


if __name__ == "__main__":
    main()
