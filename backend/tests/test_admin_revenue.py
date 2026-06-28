"""Phase 2 revenue-metrics tests: ledger-driven MRR + /revenue endpoint."""
import pytest

from app.auth.password import hash_password
from app.models.billing_ledger import BillingCharge, BillingSubscription
from app.models.organization import Organization
from app.models.user import User
from tests.conftest import auth_headers


async def _super_admin(db):
    u = User(email="rootrev@test.com", display_name="Root", password_hash=hash_password("pw12345678"),
             auth_provider="internal", role="admin", is_active=True, is_super_admin=True)
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest.mark.asyncio
async def test_metrics_mrr_from_ledger(client, db_session):
    db_session.add(BillingSubscription(stripe_subscription_id="sub_a", status="active",
                                       amount_cents=29900, quantity=2, interval="month", plan="pro"))
    sa = await _super_admin(db_session)
    resp = await client.get("/admin/v1/metrics", headers=auth_headers(sa))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mrr_from_ledger"] is True
    assert body["mrr_cents"] == 59800


@pytest.mark.asyncio
async def test_revenue_endpoint_collected(client, db_session):
    from datetime import datetime, timezone
    db_session.add(BillingCharge(stripe_charge_id="ch_a", status="succeeded", amount_cents=10000,
                                 charged_at=datetime.now(timezone.utc)))
    sa = await _super_admin(db_session)
    resp = await client.get("/admin/v1/metrics/revenue", headers=auth_headers(sa))
    assert resp.status_code == 200, resp.text
    assert resp.json()["collected_cents"] == 10000
