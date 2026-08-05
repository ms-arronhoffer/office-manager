"""Tests for resident-initiated payments in the resident portal (Phase 2.3)."""

import pytest

from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio

LEASING = "/api/v1/leasing"
RENT = "/api/v1/rent"
PORTAL = "/api/v1"


def _pt(token):
    return {"X-Resident-Token": token}


async def _seed_resident_with_lease(
    client,
    admin_user,
    sample_office,
    *,
    unit_number="3C",
    first_name="Pat",
    last_name="Payer",
    email="pat@x.com",
    rent="1000.00",
):
    unit = await client.post(
        f"{LEASING}/units",
        json={"unit_number": unit_number, "office_id": str(sample_office.id)},
        headers=auth_headers(admin_user),
    )
    unit_id = unit.json()["id"]
    resident = await client.post(
        f"{LEASING}/residents",
        json={"first_name": first_name, "last_name": last_name, "email": email},
        headers=auth_headers(admin_user),
    )
    resident_id = resident.json()["id"]
    lease = await client.post(
        f"{LEASING}/leases",
        json={
            "unit_id": unit_id,
            "status": "active",
            "rent_amount": rent,
            "security_deposit": rent,
            "occupants": [{"resident_id": resident_id, "is_primary": True}],
        },
        headers=auth_headers(admin_user),
    )
    return resident_id, lease.json()["id"]


async def _bill_lease(client, admin_user, lease_id, *, amount, period_start):
    """Create a rent charge and generate one finalized invoice for it."""
    charge = await client.post(
        f"{RENT}/charges",
        json={"resident_lease_id": lease_id, "amount": amount, "day_of_month": 1},
        headers=auth_headers(admin_user),
    )
    assert charge.status_code == 201, charge.text
    charge_id = charge.json()["id"]
    gen = await client.post(
        f"{RENT}/charges/{charge_id}/generate-invoice?period_start={period_start}",
        headers=auth_headers(admin_user),
    )
    assert gen.status_code == 200, gen.text
    return gen.json()["invoice_ids"][0]


async def _activate_portal(client, admin_user, resident_id):
    invite = await client.post(
        f"{PORTAL}/resident-portal/invite",
        json={"resident_id": resident_id},
        headers=auth_headers(admin_user),
    )
    assert invite.status_code == 200, invite.text
    session = await client.post(
        f"{PORTAL}/resident-portal/signup", json={"token": invite.json()["signup_token"]}
    )
    assert session.status_code == 200, session.text
    return session.json()["portal_token"]


async def _save_method(client, token, *, last4="4242", is_default=True):
    resp = await client.post(
        f"{PORTAL}/resident-portal/payment-methods",
        json={
            "processor_token": "pm_test_visa",
            "brand": "visa",
            "last4": last4,
            "exp_month": 12,
            "exp_year": 2030,
            "is_default": is_default,
        },
        headers=_pt(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ─── Balance ──────────────────────────────────────────────────────────────────

async def test_balance_reflects_outstanding_invoice(client, admin_user, sample_office):
    resident_id, lease_id = await _seed_resident_with_lease(client, admin_user, sample_office)
    await _bill_lease(client, admin_user, lease_id, amount="1000.00", period_start="2026-03-01")
    token = await _activate_portal(client, admin_user, resident_id)

    bal = await client.get(f"{PORTAL}/resident-portal/balance", headers=_pt(token))
    assert bal.status_code == 200, bal.text
    assert float(bal.json()["balance_due"]) == pytest.approx(1000.00)


# ─── Payment methods ──────────────────────────────────────────────────────────

async def test_save_list_and_delete_payment_method(client, admin_user, sample_office):
    resident_id, _ = await _seed_resident_with_lease(client, admin_user, sample_office)
    token = await _activate_portal(client, admin_user, resident_id)

    method_id = await _save_method(client, token)
    listed = await client.get(f"{PORTAL}/resident-portal/payment-methods", headers=_pt(token))
    assert listed.status_code == 200
    body = listed.json()
    assert len(body) == 1
    assert body[0]["last4"] == "4242"
    assert body[0]["is_default"] is True
    # The opaque processor token is never echoed back to the client.
    assert "processor_token" not in body[0]

    deleted = await client.delete(
        f"{PORTAL}/resident-portal/payment-methods/{method_id}", headers=_pt(token)
    )
    assert deleted.status_code == 204
    after = await client.get(f"{PORTAL}/resident-portal/payment-methods", headers=_pt(token))
    assert after.json() == []


async def test_raw_card_number_is_rejected(client, admin_user, sample_office):
    resident_id, _ = await _seed_resident_with_lease(client, admin_user, sample_office)
    token = await _activate_portal(client, admin_user, resident_id)
    resp = await client.post(
        f"{PORTAL}/resident-portal/payment-methods",
        json={"processor_token": "4242 4242 4242 4242", "last4": "4242"},
        headers=_pt(token),
    )
    assert resp.status_code == 422


async def test_payment_methods_require_token(client):
    resp = await client.get(f"{PORTAL}/resident-portal/payment-methods")
    assert resp.status_code == 401


# ─── Payments ─────────────────────────────────────────────────────────────────

async def test_payment_reduces_balance(client, admin_user, sample_office):
    resident_id, lease_id = await _seed_resident_with_lease(client, admin_user, sample_office)
    await _bill_lease(client, admin_user, lease_id, amount="1000.00", period_start="2026-03-01")
    token = await _activate_portal(client, admin_user, resident_id)
    method_id = await _save_method(client, token)

    pay = await client.post(
        f"{PORTAL}/resident-portal/payments",
        json={"amount": "400.00", "payment_method_id": method_id, "method": "card"},
        headers=_pt(token),
    )
    assert pay.status_code == 200, pay.text
    body = pay.json()
    assert float(body["amount_applied"]) == pytest.approx(400.00)
    assert len(body["receipt_ids"]) == 1
    assert float(body["balance"]["balance_due"]) == pytest.approx(600.00)

    bal = await client.get(f"{PORTAL}/resident-portal/balance", headers=_pt(token))
    assert float(bal.json()["balance_due"]) == pytest.approx(600.00)


async def test_payment_spans_multiple_invoices_oldest_first(
    client, admin_user, sample_office
):
    resident_id, lease_id = await _seed_resident_with_lease(client, admin_user, sample_office)
    await _bill_lease(client, admin_user, lease_id, amount="500.00", period_start="2026-01-01")
    await _bill_lease(client, admin_user, lease_id, amount="500.00", period_start="2026-02-01")
    token = await _activate_portal(client, admin_user, resident_id)
    method_id = await _save_method(client, token)

    pay = await client.post(
        f"{PORTAL}/resident-portal/payments",
        json={"amount": "750.00", "payment_method_id": method_id, "method": "card"},
        headers=_pt(token),
    )
    assert pay.status_code == 200, pay.text
    body = pay.json()
    assert len(body["receipt_ids"]) == 2
    assert float(body["balance"]["balance_due"]) == pytest.approx(250.00)


async def test_payment_over_balance_is_rejected(client, admin_user, sample_office):
    resident_id, lease_id = await _seed_resident_with_lease(client, admin_user, sample_office)
    await _bill_lease(client, admin_user, lease_id, amount="1000.00", period_start="2026-03-01")
    token = await _activate_portal(client, admin_user, resident_id)
    method_id = await _save_method(client, token)

    pay = await client.post(
        f"{PORTAL}/resident-portal/payments",
        json={"amount": "1000.01", "payment_method_id": method_id, "method": "card"},
        headers=_pt(token),
    )
    assert pay.status_code == 422, pay.text

    # Balance is untouched by the rejected attempt.
    bal = await client.get(f"{PORTAL}/resident-portal/balance", headers=_pt(token))
    assert float(bal.json()["balance_due"]) == pytest.approx(1000.00)


async def test_non_positive_payment_is_rejected(client, admin_user, sample_office):
    resident_id, lease_id = await _seed_resident_with_lease(client, admin_user, sample_office)
    await _bill_lease(client, admin_user, lease_id, amount="100.00", period_start="2026-03-01")
    token = await _activate_portal(client, admin_user, resident_id)
    pay = await client.post(
        f"{PORTAL}/resident-portal/payments",
        json={"amount": "0", "method": "card"},
        headers=_pt(token),
    )
    assert pay.status_code == 422


async def test_unconfigured_processor_records_uncaptured_payment(
    client, admin_user, sample_office
):
    """No live processor in tests: the receipt still lands, the charge does not."""
    resident_id, lease_id = await _seed_resident_with_lease(client, admin_user, sample_office)
    await _bill_lease(client, admin_user, lease_id, amount="300.00", period_start="2026-04-01")
    token = await _activate_portal(client, admin_user, resident_id)
    method_id = await _save_method(client, token)

    pay = await client.post(
        f"{PORTAL}/resident-portal/payments",
        json={"amount": "300.00", "payment_method_id": method_id, "method": "card"},
        headers=_pt(token),
    )
    assert pay.status_code == 200, pay.text
    body = pay.json()
    assert body["captured"] is False
    assert body["processor_status"] == "unconfigured"
    assert len(body["receipt_ids"]) == 1
    assert float(body["balance"]["balance_due"]) == pytest.approx(0.00)


async def test_resident_cannot_pay_against_another_residents_lease(
    client, admin_user, sample_office
):
    payer_id, payer_lease = await _seed_resident_with_lease(
        client, admin_user, sample_office, unit_number="4A", email="payer@x.com"
    )
    other_id, other_lease = await _seed_resident_with_lease(
        client,
        admin_user,
        sample_office,
        unit_number="4B",
        first_name="Other",
        last_name="Tenant",
        email="other@x.com",
    )
    await _bill_lease(client, admin_user, other_lease, amount="900.00", period_start="2026-05-01")

    payer_token = await _activate_portal(client, admin_user, payer_id)
    other_token = await _activate_portal(client, admin_user, other_id)

    # The payer has no balance of their own, so there is nothing to pay.
    assert float(
        (
            await client.get(f"{PORTAL}/resident-portal/balance", headers=_pt(payer_token))
        ).json()["balance_due"]
    ) == pytest.approx(0.00)

    attempt = await client.post(
        f"{PORTAL}/resident-portal/payments",
        json={"amount": "900.00", "method": "card"},
        headers=_pt(payer_token),
    )
    assert attempt.status_code == 409, attempt.text

    # The other resident's balance is completely unaffected.
    other_bal = await client.get(
        f"{PORTAL}/resident-portal/balance", headers=_pt(other_token)
    )
    assert float(other_bal.json()["balance_due"]) == pytest.approx(900.00)


async def test_resident_cannot_use_another_residents_payment_method(
    client, admin_user, sample_office
):
    owner_id, owner_lease = await _seed_resident_with_lease(
        client, admin_user, sample_office, unit_number="5A", email="owner@x.com"
    )
    intruder_id, intruder_lease = await _seed_resident_with_lease(
        client,
        admin_user,
        sample_office,
        unit_number="5B",
        first_name="Nosy",
        last_name="Neighbour",
        email="nosy@x.com",
    )
    await _bill_lease(
        client, admin_user, intruder_lease, amount="200.00", period_start="2026-06-01"
    )

    owner_token = await _activate_portal(client, admin_user, owner_id)
    intruder_token = await _activate_portal(client, admin_user, intruder_id)
    owner_method = await _save_method(client, owner_token)

    # Not visible.
    listed = await client.get(
        f"{PORTAL}/resident-portal/payment-methods", headers=_pt(intruder_token)
    )
    assert listed.json() == []

    # Not usable.
    pay = await client.post(
        f"{PORTAL}/resident-portal/payments",
        json={"amount": "200.00", "payment_method_id": owner_method, "method": "card"},
        headers=_pt(intruder_token),
    )
    assert pay.status_code == 404, pay.text

    # Not deletable.
    deleted = await client.delete(
        f"{PORTAL}/resident-portal/payment-methods/{owner_method}",
        headers=_pt(intruder_token),
    )
    assert deleted.status_code == 404


# ─── Autopay ──────────────────────────────────────────────────────────────────

async def test_autopay_enable_and_disable(client, admin_user, sample_office):
    resident_id, _ = await _seed_resident_with_lease(client, admin_user, sample_office)
    token = await _activate_portal(client, admin_user, resident_id)
    method_id = await _save_method(client, token)

    enabled = await client.put(
        f"{PORTAL}/resident-portal/autopay",
        json={"enabled": True, "payment_method_id": method_id},
        headers=_pt(token),
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["autopay_enabled"] is True
    assert enabled.json()["autopay_payment_method_id"] == method_id

    disabled = await client.put(
        f"{PORTAL}/resident-portal/autopay",
        json={"enabled": False},
        headers=_pt(token),
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["autopay_enabled"] is False
    assert disabled.json()["autopay_payment_method_id"] is None


async def test_autopay_requires_a_saved_method(client, admin_user, sample_office):
    resident_id, _ = await _seed_resident_with_lease(client, admin_user, sample_office)
    token = await _activate_portal(client, admin_user, resident_id)
    resp = await client.put(
        f"{PORTAL}/resident-portal/autopay",
        json={"enabled": True},
        headers=_pt(token),
    )
    assert resp.status_code == 422


async def test_autopay_rejects_another_residents_method(client, admin_user, sample_office):
    owner_id, _ = await _seed_resident_with_lease(
        client, admin_user, sample_office, unit_number="6A", email="ao@x.com"
    )
    intruder_id, _ = await _seed_resident_with_lease(
        client,
        admin_user,
        sample_office,
        unit_number="6B",
        first_name="Sneaky",
        last_name="Sam",
        email="sam@x.com",
    )
    owner_token = await _activate_portal(client, admin_user, owner_id)
    intruder_token = await _activate_portal(client, admin_user, intruder_id)
    owner_method = await _save_method(client, owner_token)

    resp = await client.put(
        f"{PORTAL}/resident-portal/autopay",
        json={"enabled": True, "payment_method_id": owner_method},
        headers=_pt(intruder_token),
    )
    assert resp.status_code == 404


async def test_deleting_method_clears_autopay(client, admin_user, sample_office):
    resident_id, _ = await _seed_resident_with_lease(client, admin_user, sample_office)
    token = await _activate_portal(client, admin_user, resident_id)
    method_id = await _save_method(client, token)
    await client.put(
        f"{PORTAL}/resident-portal/autopay",
        json={"enabled": True, "payment_method_id": method_id},
        headers=_pt(token),
    )
    deleted = await client.delete(
        f"{PORTAL}/resident-portal/payment-methods/{method_id}", headers=_pt(token)
    )
    assert deleted.status_code == 204

    off = await client.put(
        f"{PORTAL}/resident-portal/autopay", json={"enabled": False}, headers=_pt(token)
    )
    assert off.json()["autopay_enabled"] is False
    assert off.json()["autopay_payment_method_id"] is None
