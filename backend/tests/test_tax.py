"""Tests for the Tax / 1099 module (Phase 1.3)."""

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.general_ledger import GLAccount
from app.models.vendor import Vendor
from app.models.vendor_bill import VendorPayment
from app.services import gl_service, tax_service
from tests.conftest import auth_headers


# ─── Pure service-layer unit tests ───────────────────────────────────────────

def _vendor(**kw):
    defaults = dict(
        id=uuid.uuid4(),
        company_name="Acme",
        is_1099_vendor=True,
        tax_classification=None,
        default_tax_box=None,
    )
    defaults.update(kw)
    return Vendor(**defaults)


def _payment(amount, **kw):
    return VendorPayment(
        id=uuid.uuid4(),
        bill_id=uuid.uuid4(),
        payment_date=date(2025, 3, 1),
        amount=Decimal(amount),
        **kw,
    )


def test_reportable_inherits_vendor_flag():
    v = _vendor(is_1099_vendor=True)
    assert tax_service.payment_is_reportable(_payment("100"), v) is True
    v2 = _vendor(is_1099_vendor=False)
    assert tax_service.payment_is_reportable(_payment("100"), v2) is False


def test_reportable_payment_override():
    v = _vendor(is_1099_vendor=False)
    assert tax_service.payment_is_reportable(_payment("100", is_reportable=True), v) is True
    v2 = _vendor(is_1099_vendor=True)
    assert tax_service.payment_is_reportable(_payment("100", is_reportable=False), v2) is False


def test_corporations_exempt_by_default():
    v = _vendor(is_1099_vendor=True, tax_classification="c_corp")
    assert tax_service.payment_is_reportable(_payment("100"), v) is False
    # But an explicit override still forces reporting.
    assert tax_service.payment_is_reportable(_payment("100", is_reportable=True), v) is True


def test_box_resolution_override_then_default_then_nec():
    v = _vendor(default_tax_box="misc_1")
    assert tax_service.payment_box(_payment("1"), v) == "misc_1"
    assert tax_service.payment_box(_payment("1", tax_box="nec_1"), v) == "nec_1"
    v2 = _vendor(default_tax_box=None)
    assert tax_service.payment_box(_payment("1"), v2) == "nec_1"


def test_form_for_box():
    assert tax_service.form_for_box("nec_1") == "1099-NEC"
    assert tax_service.form_for_box("misc_1") == "1099-MISC"
    assert tax_service.form_for_box("unknown") == "1099-NEC"


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def expense_account(db_session: AsyncSession) -> GLAccount:
    await gl_service.seed_default_accounts(db_session, None)
    return (
        await db_session.execute(
            select(GLAccount).where(
                GLAccount.organization_id.is_(None), GLAccount.code == "6000"
            )
        )
    ).scalar_one()


@pytest_asyncio.fixture
async def vendor_1099(db_session: AsyncSession) -> Vendor:
    v = Vendor(
        id=uuid.uuid4(),
        organization_id=None,
        company_name="Reportable Contractor LLC",
        legal_name="Reportable Contractor LLC",
        is_1099_vendor=True,
        tax_id="12-3456789",
        tax_id_type="ein",
        default_tax_box="nec_1",
    )
    db_session.add(v)
    await db_session.commit()
    await db_session.refresh(v)
    return v


async def _bill_with_payment(client, headers, vendor, account, *, bill_amount, pay_amount, pay_date):
    created = (
        await client.post(
            "/api/v1/ap/bills",
            headers=headers,
            json={
                "vendor_id": str(vendor.id),
                "bill_date": pay_date,
                "lines": [{"account_id": str(account.id), "amount": bill_amount}],
            },
        )
    ).json()
    await client.post(f"/api/v1/ap/bills/{created['id']}/finalize", headers=headers)
    await client.post(
        f"/api/v1/ap/bills/{created['id']}/payments",
        headers=headers,
        json={"payment_date": pay_date, "amount": pay_amount},
    )
    return created


# ─── API tests ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_viewer_cannot_access_tax(client, viewer_user):
    resp = await client.get("/api/v1/tax/1099?year=2025", headers=auth_headers(viewer_user))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_1099_summary_aggregates_payments(
    client, accountant_user, vendor_1099, expense_account
):
    headers = auth_headers(accountant_user)
    await _bill_with_payment(
        client, headers, vendor_1099, expense_account,
        bill_amount="1000", pay_amount="1000", pay_date="2025-04-15",
    )
    resp = await client.get("/api/v1/tax/1099?year=2025", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 1
    row = body[0]
    assert row["vendor_id"] == str(vendor_1099.id)
    assert Decimal(row["total"]) == Decimal("1000.00")
    assert row["meets_threshold"] is True
    assert row["boxes"][0]["form"] == "1099-NEC"
    assert Decimal(row["boxes"][0]["amount"]) == Decimal("1000.00")


@pytest.mark.asyncio
async def test_1099_excludes_other_years(
    client, accountant_user, vendor_1099, expense_account
):
    headers = auth_headers(accountant_user)
    await _bill_with_payment(
        client, headers, vendor_1099, expense_account,
        bill_amount="1000", pay_amount="1000", pay_date="2024-06-01",
    )
    resp = await client.get("/api/v1/tax/1099?year=2025", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_1099_threshold_filter(
    client, accountant_user, vendor_1099, expense_account
):
    headers = auth_headers(accountant_user)
    await _bill_with_payment(
        client, headers, vendor_1099, expense_account,
        bill_amount="100", pay_amount="100", pay_date="2025-02-01",
    )
    # Below the $600 threshold: still listed by default...
    resp = await client.get("/api/v1/tax/1099?year=2025", headers=headers)
    assert len(resp.json()) == 1
    assert resp.json()[0]["meets_threshold"] is False
    # ...but excluded when only_reportable=true.
    resp2 = await client.get(
        "/api/v1/tax/1099?year=2025&only_reportable=true", headers=headers
    )
    assert resp2.json() == []


@pytest.mark.asyncio
async def test_1099_detail_lists_payments(
    client, accountant_user, vendor_1099, expense_account
):
    headers = auth_headers(accountant_user)
    await _bill_with_payment(
        client, headers, vendor_1099, expense_account,
        bill_amount="800", pay_amount="800", pay_date="2025-05-01",
    )
    resp = await client.get(
        f"/api/v1/tax/1099/{vendor_1099.id}?year=2025", headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert Decimal(body["total"]) == Decimal("800.00")
    assert len(body["payments"]) == 1
    assert body["payments"][0]["reportable"] is True
    assert body["payments"][0]["box"] == "nec_1"


@pytest.mark.asyncio
async def test_1099_export_csv(
    client, accountant_user, vendor_1099, expense_account
):
    headers = auth_headers(accountant_user)
    await _bill_with_payment(
        client, headers, vendor_1099, expense_account,
        bill_amount="1200", pay_amount="1200", pay_date="2025-07-01",
    )
    resp = await client.get(
        "/api/v1/tax/1099/export?year=2025", headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    text = resp.text
    assert "Reportable Contractor LLC" in text
    assert "1099-NEC" in text
    assert "1200.00" in text


@pytest.mark.asyncio
async def test_1099_detail_unknown_vendor(client, accountant_user):
    headers = auth_headers(accountant_user)
    resp = await client.get(
        f"/api/v1/tax/1099/{uuid.uuid4()}?year=2025", headers=headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_invalid_year_rejected(client, accountant_user):
    headers = auth_headers(accountant_user)
    resp = await client.get("/api/v1/tax/1099?year=1800", headers=headers)
    assert resp.status_code == 422
