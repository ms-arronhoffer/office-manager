"""Phase 4 tests: invoice CSV export + reconciliation report."""
import pytest

from app.auth.password import hash_password
from app.models.billing_ledger import BillingInvoice, BillingSubscription
from app.models.organization import Organization
from app.models.user import User
from tests.conftest import auth_headers


async def _sa(db):
    sa = User(email="rootp4@test.com", display_name="Root", password_hash=hash_password("pw12345678"),
              auth_provider="internal", role="admin", is_active=True, is_super_admin=True)
    db.add(sa)
    await db.commit()
    await db.refresh(sa)
    return sa


@pytest.mark.asyncio
async def test_export_invoices_csv(client, db_session):
    sa = await _sa(db_session)
    db_session.add(BillingInvoice(stripe_invoice_id="in_x", status="paid", total_cents=29900,
                                  tax_cents=2400, currency="usd", number="A-1"))
    await db_session.commit()
    r = await client.get("/admin/v1/billing/export/invoices", headers=auth_headers(sa))
    assert r.status_code == 200
    assert "tax_cents" in r.text and "A-1" in r.text


@pytest.mark.asyncio
async def test_reconcile_detects_drift(client, db_session):
    org = Organization(name="DriftCo", slug="driftco", plan="pro", payment_status="canceled", is_active=False)
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    db_session.add(BillingSubscription(organization_id=org.id, status="active", amount_cents=29900))
    sa = await _sa(db_session)
    r = await client.get("/admin/v1/billing/reconcile", headers=auth_headers(sa))
    assert r.status_code == 200, r.text
    assert r.json()["drift_count"] == 1
