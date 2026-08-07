"""Daily resident autopay invoice generation and debit execution."""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import async_session
from app.models.customer_invoice import CustomerInvoice
from app.models.organization import Organization
from app.models.rent import RentCharge
from app.models.resident import ResidentLease, ResidentLeaseOccupant
from app.models.resident_payment_attempt import ResidentPaymentAttempt
from app.models.resident_payment_method import ResidentPaymentMethod
from app.services import ar_service, organization_integration_settings, rent_service
from app.services import resident_ach_service
from app.utils import payment_processor
from app.utils.rls import set_session_org, set_system_bypass

logger = logging.getLogger(__name__)


def _attempt_key(lease_id: uuid.UUID, invoice_ids: list[uuid.UUID]) -> str:
    material = f"resident-autopay:{lease_id}:" + ":".join(sorted(map(str, invoice_ids)))
    return "resident-autopay:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def _pending_blocks_new_debit(attempt: ResidentPaymentAttempt | None) -> bool:
    return attempt is not None and bool(attempt.processor_ref)


async def _due_invoices(
    db: AsyncSession,
    lease: ResidentLease,
    customer_id: uuid.UUID,
    as_of: date,
) -> list[CustomerInvoice]:
    charge_ids = (
        await db.execute(
            select(RentCharge.id).where(
                RentCharge.organization_id == lease.organization_id,
                RentCharge.resident_lease_id == lease.id,
                RentCharge.active.is_(True),
                RentCharge.is_deleted.is_(False),
            )
        )
    ).scalars().all()
    if not charge_ids:
        return []
    source_filters = [
        CustomerInvoice.source_ref.startswith(f"rentcharge:{charge_id}:")
        for charge_id in charge_ids
    ]
    invoices = (
        await db.execute(
            select(CustomerInvoice)
            .where(
                CustomerInvoice.organization_id == lease.organization_id,
                CustomerInvoice.customer_id == customer_id,
                CustomerInvoice.source == rent_service.RENT_INVOICE_SOURCE,
                CustomerInvoice.status == "finalized",
                CustomerInvoice.due_date <= as_of,
                or_(*source_filters),
            )
            .options(selectinload(CustomerInvoice.lines), selectinload(CustomerInvoice.receipts))
            .order_by(CustomerInvoice.due_date, CustomerInvoice.created_at)
        )
    ).scalars().unique().all()
    return [invoice for invoice in invoices if ar_service.balance_due(invoice) > 0]


async def _run_lease_autopay(
    db: AsyncSession,
    lease: ResidentLease,
    method: ResidentPaymentMethod,
    *,
    as_of: date,
) -> str:
    resident = rent_service.primary_resident(lease)
    if resident is None or resident.customer_id is None:
        return "skipped"
    pending_attempt = (
        await db.execute(
            select(ResidentPaymentAttempt)
            .where(
                ResidentPaymentAttempt.organization_id == lease.organization_id,
                ResidentPaymentAttempt.lease_id == lease.id,
                ResidentPaymentAttempt.status == "processing",
                ResidentPaymentAttempt.idempotency_key.startswith("resident-autopay:"),
            )
            .order_by(ResidentPaymentAttempt.created_at.desc())
        )
    ).scalars().first()
    if _pending_blocks_new_debit(pending_attempt):
        return "processing"
    invoices = await _due_invoices(db, lease, resident.customer_id, as_of)
    if not invoices:
        return "skipped"

    allocations = [
        {"invoice_id": str(invoice.id), "amount": str(ar_service.balance_due(invoice))}
        for invoice in invoices
    ]
    amount = sum((Decimal(item["amount"]) for item in allocations), Decimal("0.00"))
    key = _attempt_key(lease.id, [invoice.id for invoice in invoices])
    attempt = pending_attempt or (
        await db.execute(
            select(ResidentPaymentAttempt).where(
                ResidentPaymentAttempt.organization_id == lease.organization_id,
                ResidentPaymentAttempt.idempotency_key == key,
            )
        )
    ).scalar_one_or_none()
    if attempt is not None and (attempt.processor_ref or attempt.status != "processing"):
        return attempt.status
    if attempt is None:
        attempt = ResidentPaymentAttempt(
            id=uuid.uuid4(),
            organization_id=lease.organization_id,
            resident_id=resident.id,
            lease_id=lease.id,
            invoice_id=invoices[0].id,
            payment_method_id=method.id,
            amount=amount,
            method_type=method.method_type,
            idempotency_key=key,
            status="processing",
            allocation_json=allocations,
        )
        db.add(attempt)
        await db.commit()
        await set_session_org(db, lease.organization_id)
    else:
        amount = attempt.amount
        key = attempt.idempotency_key

    config = await organization_integration_settings.resolve(
        db, lease.organization_id, "resident_payments"
    )
    result = await payment_processor.charge_payment(
        amount,
        method=method.method_type,
        payment_token=method.processor_token,
        stripe_customer_id=method.stripe_customer_id,
        description=f"Scheduled resident payment for lease {lease.id}",
        idempotency_key=key,
        metadata={"resident_payment_attempt_id": str(attempt.id), "autopay": "true"},
        config=config,
    )
    attempt = (
        await db.execute(
            select(ResidentPaymentAttempt)
            .where(ResidentPaymentAttempt.id == attempt.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    attempt.processor_ref = attempt.processor_ref or result.processor_ref
    if result.status == "succeeded":
        await resident_ach_service.settle_attempt(db, attempt)
    elif result.status == "processing":
        pass
    else:
        attempt.status = "failed"
        attempt.failure_detail = result.detail or "The scheduled payment was not accepted."
        attempt.failed_at = datetime.now(timezone.utc)
        method.failure_count += 1
        method.last_failed_at = datetime.now(timezone.utc)
    await db.commit()
    return attempt.status


async def run_resident_autopay(*, as_of: date | None = None) -> dict[str, int]:
    """Generate due rent invoices and execute authorized resident debits."""
    as_of = as_of or date.today()
    counts = {"succeeded": 0, "processing": 0, "failed": 0, "skipped": 0}
    async with async_session() as db:
        await set_system_bypass(db)
        organization_ids = (
            await db.execute(select(Organization.id).where(Organization.is_active.is_(True)))
        ).scalars().all()
        await db.commit()

    for organization_id in organization_ids:
        async with async_session() as db:
            try:
                await set_session_org(db, organization_id)
                await rent_service.run_recurring_billing(db, organization_id, as_of=as_of)
                await set_session_org(db, organization_id)
                leases = (
                    await db.execute(
                        select(ResidentLease)
                        .where(
                            ResidentLease.organization_id == organization_id,
                            ResidentLease.status == "active",
                            ResidentLease.is_deleted.is_(False),
                            ResidentLease.autopay_enabled.is_(True),
                            ResidentLease.autopay_payment_method_id.is_not(None),
                        )
                        .options(
                            selectinload(ResidentLease.occupants).selectinload(
                                ResidentLeaseOccupant.resident
                            ),
                            selectinload(ResidentLease.unit),
                        )
                    )
                ).scalars().unique().all()
                for lease in leases:
                    method = await db.get(ResidentPaymentMethod, lease.autopay_payment_method_id)
                    if (
                        method is None
                        or method.organization_id != organization_id
                        or method.status != "active"
                        or method.method_type != "ach"
                        or method.consent_version != resident_ach_service.ACH_CONSENT_VERSION
                        or lease.autopay_consent_version != resident_ach_service.AUTOPAY_CONSENT_VERSION
                    ):
                        counts["skipped"] += 1
                        continue
                    outcome = await _run_lease_autopay(db, lease, method, as_of=as_of)
                    counts[outcome if outcome in counts else "skipped"] += 1
            except Exception:
                await db.rollback()
                counts["failed"] += 1
                logger.exception("Resident autopay failed for organization %s", organization_id)
    logger.info("Resident autopay completed", extra=counts)
    return counts
