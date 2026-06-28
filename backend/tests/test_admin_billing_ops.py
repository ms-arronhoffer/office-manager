"""Phase 3 admin billing-ops tests: detail, credit, extend-trial."""
import pytest

from app.auth.password import hash_password
from app.models.billing_ledger import BillingCharge, BillingSubscription
from app.models.organization import Organization
from app.models.user import User
from tests.conftest import auth_headers


async def _setup(db):
    org = Organization(name="OpsCo", slug="opsco", plan="pro", is_active=True,
                       stripe_customer_id="cus_ops")
    db.add(org)
    sa = User(email="rootops@test.com", display_name="Root", password_hash=hash_password("pw12345678"),
              auth_provider="internal", role="admin", is_active=True, is_super_admin=True)
    db.add(sa)
    await db.commit()
    await db.refresh(org)
    await db.refresh(sa)
    return org, sa


@pytest.mark.asyncio
async def test_billing_detail_aggregates(client, db_session):
    org, sa = await _setup(db_session)
    db_session.add(BillingSubscription(organization_id=org.id, status="active", plan="pro",
                                       amount_cents=29900, quantity=1))
    db_session.add(BillingCharge(organization_id=org.id, status="succeeded", amount_cents=29900))
    await db_session.commit()
    resp = await client.get(f"/admin/v1/billing/{org.id}/detail", headers=auth_headers(sa))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["subscriptions"]) == 1 and len(body["charges"]) == 1


@pytest.mark.asyncio
async def test_issue_credit_and_balance(client, db_session):
    org, sa = await _setup(db_session)
    r = await client.post(f"/admin/v1/billing/{org.id}/credit", headers=auth_headers(sa),
                          json={"amount_cents": 5000, "reason": "goodwill"})
    assert r.status_code == 201, r.text
    d = await client.get(f"/admin/v1/billing/{org.id}/detail", headers=auth_headers(sa))
    assert d.json()["credit_balance_cents"] == 5000


@pytest.mark.asyncio
async def test_extend_trial(client, db_session):
    org, sa = await _setup(db_session)
    r = await client.post(f"/admin/v1/billing/{org.id}/extend-trial", headers=auth_headers(sa),
                          json={"days": 14})
    assert r.status_code == 200, r.text
    assert r.json()["trial_ends_at"] is not None
