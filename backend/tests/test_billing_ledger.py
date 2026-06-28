"""Phase 1 billing-ledger tests: upsert helpers + webhook idempotency."""
import pytest
from sqlalchemy import func, select

from app.models.billing_ledger import (
    BillingCharge,
    BillingCoupon,
    BillingInvoice,
    BillingRefund,
    BillingSubscription,
)
from app.models.organization import Organization
from app.services import billing_ledger_service as ledger


@pytest.mark.asyncio
async def test_upsert_invoice_is_idempotent_and_links_org(db_session):
    org = Organization(name="Acme", slug="acme", plan="pro", is_active=True,
                        stripe_customer_id="cus_1")
    db_session.add(org)
    await db_session.commit()

    inv = {"id": "in_1", "customer": "cus_1", "subscription": "sub_1", "status": "paid",
           "currency": "usd", "subtotal": 29900, "tax": 0, "total": 29900,
           "amount_paid": 29900, "amount_due": 0, "created": 1700000000}
    await ledger.upsert_invoice(db_session, inv)
    await ledger.upsert_invoice(db_session, {**inv, "status": "paid", "amount_paid": 29900})
    await db_session.commit()

    rows = (await db_session.execute(select(BillingInvoice))).scalars().all()
    assert len(rows) == 1
    assert rows[0].total_cents == 29900
    assert rows[0].organization_id == org.id
    assert rows[0].source == "stripe"


@pytest.mark.asyncio
async def test_upsert_charge_and_refund_inherit_org(db_session):
    org = Organization(name="Beta", slug="beta", plan="pro", is_active=True,
                        stripe_customer_id="cus_2")
    db_session.add(org)
    await db_session.commit()

    await ledger.upsert_charge(db_session, {"id": "ch_1", "customer": "cus_2",
                                            "amount": 9900, "status": "succeeded", "created": 1700000000})
    await ledger.upsert_refund(db_session, {"id": "re_1", "charge": "ch_1", "amount": 500,
                                            "status": "succeeded", "created": 1700000100})
    await db_session.commit()

    charge = (await db_session.execute(select(BillingCharge))).scalar_one()
    refund = (await db_session.execute(select(BillingRefund))).scalar_one()
    assert charge.organization_id == org.id
    assert refund.organization_id == org.id
    assert refund.amount_cents == 500


@pytest.mark.asyncio
async def test_upsert_coupon(db_session):
    await ledger.upsert_coupon(db_session, {"id": "cp_1", "name": "LAUNCH", "percent_off": 20,
                                            "duration": "once", "valid": True})
    await db_session.commit()
    coupon = (await db_session.execute(select(BillingCoupon))).scalar_one()
    assert coupon.code == "LAUNCH"
    assert coupon.percent_off == 20


@pytest.mark.asyncio
async def test_subscription_count(db_session):
    await ledger.upsert_subscription(db_session, {
        "id": "sub_9", "customer": "cus_x", "status": "active",
        "items": {"data": [{"quantity": 3, "price": {"unit_amount": 29900, "currency": "usd",
                                                       "recurring": {"interval": "month"}}}]},
    })
    await db_session.commit()
    total = (await db_session.execute(select(func.count()).select_from(BillingSubscription))).scalar_one()
    assert total == 1
