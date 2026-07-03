"""Tests for rent collection & payments-in (Phase 2.3)."""

import pytest

from tests.conftest import auth_headers

pytestmark = pytest.mark.asyncio

LEASING = "/api/v1/leasing"
RENT = "/api/v1/rent"
AR = "/api/v1/ar"


async def _seed_lease(client, admin_user, sample_office, *, rent="1500.00", deposit="1500.00"):
    unit = await client.post(
        f"{LEASING}/units",
        json={"unit_number": "2B", "office_id": str(sample_office.id)},
        headers=auth_headers(admin_user),
    )
    unit_id = unit.json()["id"]
    resident = await client.post(
        f"{LEASING}/residents",
        json={"first_name": "Rhea", "last_name": "Renter", "email": "rhea@x.com"},
        headers=auth_headers(admin_user),
    )
    resident_id = resident.json()["id"]
    lease = await client.post(
        f"{LEASING}/leases",
        json={
            "unit_id": unit_id,
            "status": "active",
            "rent_amount": rent,
            "security_deposit": deposit,
            "occupants": [{"resident_id": resident_id, "is_primary": True}],
        },
        headers=auth_headers(admin_user),
    )
    return lease.json()["id"], resident_id


async def test_create_and_list_rent_charge(client, admin_user, sample_office):
    lease_id, _ = await _seed_lease(client, admin_user, sample_office)
    resp = await client.post(
        f"{RENT}/charges",
        json={"resident_lease_id": lease_id, "amount": "1500.00", "day_of_month": 1},
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["charge_type"] == "rent"

    listed = await client.get(f"{RENT}/charges", headers=auth_headers(admin_user))
    assert listed.status_code == 200
    assert len(listed.json()) == 1


async def test_charge_rejects_bad_enum_and_amount(client, admin_user, sample_office):
    lease_id, _ = await _seed_lease(client, admin_user, sample_office)
    bad_type = await client.post(
        f"{RENT}/charges",
        json={"resident_lease_id": lease_id, "amount": "10", "charge_type": "bogus"},
        headers=auth_headers(admin_user),
    )
    assert bad_type.status_code == 422
    bad_amt = await client.post(
        f"{RENT}/charges",
        json={"resident_lease_id": lease_id, "amount": "0"},
        headers=auth_headers(admin_user),
    )
    assert bad_amt.status_code == 422


async def test_generate_invoice_posts_to_gl_and_ar(client, admin_user, sample_office):
    lease_id, _ = await _seed_lease(client, admin_user, sample_office)
    charge = await client.post(
        f"{RENT}/charges",
        json={"resident_lease_id": lease_id, "amount": "1500.00", "day_of_month": 1},
        headers=auth_headers(admin_user),
    )
    charge_id = charge.json()["id"]
    gen = await client.post(
        f"{RENT}/charges/{charge_id}/generate-invoice?period_start=2026-03-01",
        headers=auth_headers(admin_user),
    )
    assert gen.status_code == 200, gen.text
    assert gen.json()["generated"] == 1

    # Regenerating the same period is idempotent.
    again = await client.post(
        f"{RENT}/charges/{charge_id}/generate-invoice?period_start=2026-03-01",
        headers=auth_headers(admin_user),
    )
    assert again.json()["generated"] == 0

    # The invoice appears in the AR aging report as an outstanding balance.
    aging = await client.get(f"{AR}/aging", headers=auth_headers(admin_user))
    assert aging.status_code == 200
    assert float(aging.json()["grand_total"]) == pytest.approx(1500.00)


async def test_run_billing_generates_due_periods(client, admin_user, sample_office):
    lease_id, _ = await _seed_lease(client, admin_user, sample_office)
    await client.post(
        f"{RENT}/charges",
        json={
            "resident_lease_id": lease_id,
            "amount": "1000.00",
            "day_of_month": 1,
            "start_date": "2026-01-01",
        },
        headers=auth_headers(admin_user),
    )
    run = await client.post(
        f"{RENT}/run-billing?as_of=2026-03-15", headers=auth_headers(admin_user)
    )
    assert run.status_code == 200, run.text
    # Jan, Feb, Mar due by 2026-03-15.
    assert run.json()["generated"] == 3

    # Running again bills nothing new.
    rerun = await client.post(
        f"{RENT}/run-billing?as_of=2026-03-15", headers=auth_headers(admin_user)
    )
    assert rerun.json()["generated"] == 0


async def test_record_payment_offline(client, admin_user, sample_office):
    lease_id, _ = await _seed_lease(client, admin_user, sample_office)
    charge = await client.post(
        f"{RENT}/charges",
        json={"resident_lease_id": lease_id, "amount": "1200.00"},
        headers=auth_headers(admin_user),
    )
    charge_id = charge.json()["id"]
    gen = await client.post(
        f"{RENT}/charges/{charge_id}/generate-invoice?period_start=2026-04-01",
        headers=auth_headers(admin_user),
    )
    invoice_id = gen.json()["invoice_ids"][0]

    pay = await client.post(
        f"{RENT}/payments",
        json={"invoice_id": invoice_id, "amount": "1200.00", "method": "check"},
        headers=auth_headers(admin_user),
    )
    assert pay.status_code == 201, pay.text
    assert pay.json()["captured"] is False
    assert pay.json()["processor_status"] == "offline"

    # Invoice is now fully paid → no longer outstanding in aging.
    aging = await client.get(f"{AR}/aging", headers=auth_headers(admin_user))
    assert float(aging.json()["grand_total"]) == pytest.approx(0.0)


async def test_card_payment_without_processor_reports_unconfigured(
    client, admin_user, sample_office
):
    lease_id, _ = await _seed_lease(client, admin_user, sample_office)
    charge = await client.post(
        f"{RENT}/charges",
        json={"resident_lease_id": lease_id, "amount": "500.00"},
        headers=auth_headers(admin_user),
    )
    charge_id = charge.json()["id"]
    gen = await client.post(
        f"{RENT}/charges/{charge_id}/generate-invoice?period_start=2026-05-01",
        headers=auth_headers(admin_user),
    )
    invoice_id = gen.json()["invoice_ids"][0]
    pay = await client.post(
        f"{RENT}/payments",
        json={
            "invoice_id": invoice_id,
            "amount": "500.00",
            "method": "card",
            "payment_token": "tok_test",
        },
        headers=auth_headers(admin_user),
    )
    assert pay.status_code == 201, pay.text
    # Processor unconfigured in tests → not captured, but receipt still recorded.
    assert pay.json()["captured"] is False
    assert pay.json()["processor_status"] == "unconfigured"


async def test_late_fee_automation(client, admin_user, sample_office):
    lease_id, _ = await _seed_lease(client, admin_user, sample_office)
    charge = await client.post(
        f"{RENT}/charges",
        json={
            "resident_lease_id": lease_id,
            "amount": "1000.00",
            "day_of_month": 1,
            "grace_days": 5,
            "late_fee_type": "flat",
            "late_fee_amount": "75.00",
        },
        headers=auth_headers(admin_user),
    )
    charge_id = charge.json()["id"]
    await client.post(
        f"{RENT}/charges/{charge_id}/generate-invoice?period_start=2026-06-01",
        headers=auth_headers(admin_user),
    )
    # 2026-06-01 due + 5 grace → overdue by 2026-06-20.
    late = await client.post(
        f"{RENT}/apply-late-fees?as_of=2026-06-20", headers=auth_headers(admin_user)
    )
    assert late.status_code == 200, late.text
    assert late.json()["assessed"] == 1

    # Idempotent — no duplicate late fee.
    again = await client.post(
        f"{RENT}/apply-late-fees?as_of=2026-06-21", headers=auth_headers(admin_user)
    )
    assert again.json()["assessed"] == 0

    # Rent + late fee outstanding.
    aging = await client.get(f"{AR}/aging", headers=auth_headers(admin_user))
    assert float(aging.json()["grand_total"]) == pytest.approx(1075.00)


async def test_no_late_fee_before_grace(client, admin_user, sample_office):
    lease_id, _ = await _seed_lease(client, admin_user, sample_office)
    charge = await client.post(
        f"{RENT}/charges",
        json={
            "resident_lease_id": lease_id,
            "amount": "1000.00",
            "day_of_month": 1,
            "grace_days": 5,
            "late_fee_type": "flat",
            "late_fee_amount": "75.00",
        },
        headers=auth_headers(admin_user),
    )
    charge_id = charge.json()["id"]
    await client.post(
        f"{RENT}/charges/{charge_id}/generate-invoice?period_start=2026-06-01",
        headers=auth_headers(admin_user),
    )
    late = await client.post(
        f"{RENT}/apply-late-fees?as_of=2026-06-04", headers=auth_headers(admin_user)
    )
    assert late.json()["assessed"] == 0


async def test_security_deposit_hold_and_return(client, admin_user, sample_office):
    lease_id, _ = await _seed_lease(client, admin_user, sample_office)
    dep = await client.post(
        f"{RENT}/deposits",
        json={"resident_lease_id": lease_id, "amount": "1500.00", "held_date": "2026-01-01"},
        headers=auth_headers(admin_user),
    )
    assert dep.status_code == 201, dep.text
    dep_id = dep.json()["id"]
    assert dep.json()["status"] == "held"

    # Return 1200, forfeit 300.
    ret = await client.post(
        f"{RENT}/deposits/{dep_id}/return",
        json={"returned_amount": "1200.00", "forfeited_amount": "300.00", "returned_date": "2026-12-31"},
        headers=auth_headers(admin_user),
    )
    assert ret.status_code == 200, ret.text
    assert ret.json()["status"] == "returned"
    assert ret.json()["returned_amount"] == "1200.00"
    assert ret.json()["forfeited_amount"] == "300.00"


async def test_deposit_return_cannot_exceed_held(client, admin_user, sample_office):
    lease_id, _ = await _seed_lease(client, admin_user, sample_office)
    dep = await client.post(
        f"{RENT}/deposits",
        json={"resident_lease_id": lease_id, "amount": "1000.00"},
        headers=auth_headers(admin_user),
    )
    dep_id = dep.json()["id"]
    over = await client.post(
        f"{RENT}/deposits/{dep_id}/return",
        json={"returned_amount": "1500.00"},
        headers=auth_headers(admin_user),
    )
    assert over.status_code == 409


async def test_deposit_partial_then_full_return(client, admin_user, sample_office):
    lease_id, _ = await _seed_lease(client, admin_user, sample_office)
    dep = await client.post(
        f"{RENT}/deposits",
        json={"resident_lease_id": lease_id, "amount": "1000.00"},
        headers=auth_headers(admin_user),
    )
    dep_id = dep.json()["id"]
    first = await client.post(
        f"{RENT}/deposits/{dep_id}/return",
        json={"returned_amount": "400.00"},
        headers=auth_headers(admin_user),
    )
    assert first.json()["status"] == "partially_returned"
    second = await client.post(
        f"{RENT}/deposits/{dep_id}/return",
        json={"returned_amount": "600.00"},
        headers=auth_headers(admin_user),
    )
    assert second.json()["status"] == "returned"


async def test_rent_endpoints_require_finance_role(client, viewer_user, sample_office):
    resp = await client.get(f"{RENT}/charges", headers=auth_headers(viewer_user))
    assert resp.status_code == 403
