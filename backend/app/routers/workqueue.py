"""Personal work queue — ``/api/v1/work-queue``.

Answers the only question most users open the product to ask: *what needs me
today?* Rather than making someone tour Commercial, Maintenance, Finance and
Transitions to assemble that list themselves, this router gathers the open
obligations that belong to the caller and returns them as one ranked feed.

Every item carries the same shape (``kind``, ``title``, ``due_date``,
``urgency``, ``link``) so the UI can render a single queue, and each entry
deep-links back to the record where the work is actually done.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.customer_invoice import CustomerInvoice
from app.models.lease import Lease
from app.models.lease_option import LeaseOption
from app.models.lease_renewal import LeaseRenewal
from app.models.maintenance_ticket import MaintenanceTicket
from app.models.procurement import PurchaseRequisition
from app.models.transition import OfficeTransition, TransitionChecklistItem
from app.models.user import User
from app.models.vendor_bill import VendorBill
from app.services import renewal_service

router = APIRouter()

# Ranking used to sort the merged feed; lower sorts first.
_URGENCY_RANK = {
    "overdue": 0,
    "critical": 1,
    "urgent": 2,
    "upcoming": 3,
    "unscheduled": 4,
}


class WorkItem(BaseModel):
    id: uuid.UUID
    kind: str
    category: str
    title: str
    detail: str | None = None
    due_date: date | None = None
    days_remaining: int | None = None
    urgency: str
    link: str


class WorkQueueResponse(BaseModel):
    items: list[WorkItem]
    counts: dict[str, int]


def _sort_key(item: WorkItem) -> tuple[int, int]:
    return (
        _URGENCY_RANK.get(item.urgency, 5),
        item.days_remaining if item.days_remaining is not None else 10_000,
    )


def _due(due_date: date | None, today: date) -> tuple[int | None, str]:
    days = renewal_service.days_remaining(due_date, today)
    return days, renewal_service.urgency(days)


async def _approval_items(
    db: AsyncSession, user: User, today: date
) -> list[WorkItem]:
    """Finance documents waiting on a signature this user is able to give.

    Documents the caller prepared or submitted are deliberately excluded: they
    cannot approve their own work, so showing them would be noise.
    """
    if user.role not in ("admin", "accountant") and not user.is_super_admin:
        return []

    items: list[WorkItem] = []
    org_id = user.organization_id

    def _not_own(model):
        return (
            or_(model.prepared_by_id.is_(None), model.prepared_by_id != user.id),
            or_(model.submitted_by_id.is_(None), model.submitted_by_id != user.id),
        )

    bills = (
        (
            await db.execute(
                select(VendorBill).where(
                    VendorBill.organization_id == org_id,
                    VendorBill.approval_status == "pending",
                    VendorBill.status == "draft",
                    *_not_own(VendorBill),
                )
            )
        )
        .scalars()
        .all()
    )
    for bill in bills:
        days, urgency = _due(bill.due_date, today)
        items.append(
            WorkItem(
                id=bill.id,
                kind="bill_approval",
                category="Finance",
                title="Vendor bill awaiting approval",
                detail=f"{bill.bill_number or 'Bill'} — {bill.total_amount}",
                due_date=bill.due_date,
                days_remaining=days,
                urgency=urgency if bill.due_date else "critical",
                link="/accounts-payable",
            )
        )

    invoices = (
        (
            await db.execute(
                select(CustomerInvoice).where(
                    CustomerInvoice.organization_id == org_id,
                    CustomerInvoice.approval_status == "pending",
                    CustomerInvoice.status == "draft",
                    *_not_own(CustomerInvoice),
                )
            )
        )
        .scalars()
        .all()
    )
    for invoice in invoices:
        days, urgency = _due(invoice.due_date, today)
        items.append(
            WorkItem(
                id=invoice.id,
                kind="invoice_approval",
                category="Finance",
                title="Customer invoice awaiting approval",
                detail=f"{invoice.invoice_number or 'Invoice'} — {invoice.total_amount}",
                due_date=invoice.due_date,
                days_remaining=days,
                urgency=urgency if invoice.due_date else "critical",
                link="/accounts-receivable",
            )
        )

    requisitions = (
        (
            await db.execute(
                select(PurchaseRequisition).where(
                    PurchaseRequisition.organization_id == org_id,
                    PurchaseRequisition.approval_status == "pending",
                    PurchaseRequisition.is_deleted.is_(False),
                    *_not_own(PurchaseRequisition),
                )
            )
        )
        .scalars()
        .all()
    )
    for req in requisitions:
        days, urgency = _due(req.needed_by, today)
        items.append(
            WorkItem(
                id=req.id,
                kind="requisition_approval",
                category="Procurement",
                title="Purchase requisition awaiting approval",
                detail=f"{req.title} — {req.estimated_total}",
                due_date=req.needed_by,
                days_remaining=days,
                urgency=urgency if req.needed_by else "critical",
                link=f"/procurement/requisitions/{req.id}",
            )
        )
    return items


async def _renewal_items(db: AsyncSession, user: User, today: date) -> list[WorkItem]:
    """Renewals and options this user owns that still need a decision."""
    org_id = user.organization_id
    items: list[WorkItem] = []

    rows = (
        (
            await db.execute(
                select(LeaseRenewal, Lease)
                .join(Lease, Lease.id == LeaseRenewal.lease_id)
                .where(
                    Lease.organization_id == org_id,
                    Lease.is_deleted.is_(False),
                    LeaseRenewal.status.in_(renewal_service.OPEN_RENEWAL_STATUSES),
                    LeaseRenewal.executed_at.is_(None),
                    or_(
                        LeaseRenewal.owner_id == user.id,
                        LeaseRenewal.owner_id.is_(None),
                    ),
                )
            )
        )
        .all()
    )
    for renewal, lease in rows:
        due = renewal.notice_due_date or renewal_service.notice_due_date(lease)
        days, urgency = _due(due, today)
        action = (
            "Serve renewal notice"
            if renewal.notice_sent_at is None
            else "Agree renewal terms"
        )
        items.append(
            WorkItem(
                id=renewal.id,
                kind="lease_renewal",
                category="Leases",
                title=action,
                detail=lease.lease_name
                + ("" if renewal.owner_id else " (unassigned)"),
                due_date=due,
                days_remaining=days,
                urgency=urgency,
                link=f"/leases/{lease.id}",
            )
        )

    options = (
        (
            await db.execute(
                select(LeaseOption, Lease)
                .join(Lease, Lease.id == LeaseOption.lease_id)
                .where(
                    Lease.organization_id == org_id,
                    Lease.is_deleted.is_(False),
                    LeaseOption.status == "open",
                    LeaseOption.exercise_window_end.isnot(None),
                )
            )
        )
        .all()
    )
    for option, lease in options:
        days, urgency = _due(option.exercise_window_end, today)
        if urgency == "upcoming":
            continue
        items.append(
            WorkItem(
                id=option.id,
                kind="lease_option",
                category="Leases",
                title=f"{option.option_type.title()} option window closing",
                detail=lease.lease_name,
                due_date=option.exercise_window_end,
                days_remaining=days,
                urgency=urgency,
                link=f"/leases/{lease.id}",
            )
        )
    return items


async def _transition_items(db: AsyncSession, user: User, today: date) -> list[WorkItem]:
    """Transition checklist tasks assigned to this user."""
    rows = (
        (
            await db.execute(
                select(TransitionChecklistItem, OfficeTransition)
                .join(
                    OfficeTransition,
                    OfficeTransition.id == TransitionChecklistItem.transition_id,
                )
                .where(
                    OfficeTransition.organization_id == user.organization_id,
                    OfficeTransition.is_deleted.is_(False),
                    TransitionChecklistItem.is_complete.is_(False),
                    TransitionChecklistItem.assigned_to_id == user.id,
                )
            )
        )
        .all()
    )
    items: list[WorkItem] = []
    for item, transition in rows:
        days, urgency = _due(item.due_date, today)
        items.append(
            WorkItem(
                id=item.id,
                kind="transition_task",
                category="Transitions",
                title=item.item_label,
                detail=transition.sheet_name or transition.transition_type,
                due_date=item.due_date,
                days_remaining=days,
                urgency=urgency,
                link=f"/transitions/{transition.id}",
            )
        )
    return items


async def _ticket_items(db: AsyncSession, user: User, today: date) -> list[WorkItem]:
    """High-priority maintenance still open, so nothing urgent is buried."""
    tickets = (
        (
            await db.execute(
                select(MaintenanceTicket)
                .where(
                    MaintenanceTicket.organization_id == user.organization_id,
                    MaintenanceTicket.is_deleted.is_(False),
                    MaintenanceTicket.status.in_(("open", "in_progress")),
                    MaintenanceTicket.priority.in_(("high", "urgent", "critical")),
                )
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return [
        WorkItem(
            id=ticket.id,
            kind="maintenance_ticket",
            category="Maintenance",
            title=ticket.subject,
            detail=f"{ticket.priority} priority, {ticket.status}",
            due_date=None,
            days_remaining=None,
            urgency="critical",
            link=f"/maintenance-tickets/{ticket.id}",
        )
        for ticket in tickets
    ]


@router.get("", response_model=WorkQueueResponse)
async def get_work_queue(
    limit: int = Query(default=100, ge=1, le=500),
    category: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Everything currently waiting on this user, ranked by urgency."""
    today = date.today()
    items: list[WorkItem] = []
    items.extend(await _approval_items(db, current_user, today))
    items.extend(await _renewal_items(db, current_user, today))
    items.extend(await _transition_items(db, current_user, today))
    items.extend(await _ticket_items(db, current_user, today))

    if category:
        items = [item for item in items if item.category.lower() == category.lower()]

    items.sort(key=_sort_key)

    counts: dict[str, int] = {}
    for item in items:
        counts[item.category] = counts.get(item.category, 0) + 1
        counts[item.urgency] = counts.get(item.urgency, 0) + 1
    counts["total"] = len(items)

    return WorkQueueResponse(items=items[:limit], counts=counts)
