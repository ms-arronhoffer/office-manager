import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lease import Lease
from app.services.lease_lifecycle_service import (
    compute_lifecycle_event,
    present_value_remaining,
    LifecycleError,
)
from tests.conftest import auth_headers


# ─── Pure compute-engine unit tests ──────────────────────────────────────────

def test_present_value_matches_schedule_convention():
    # 12 monthly payments of 1000 at 5% annual (compound monthly).
    pv = present_value_remaining(payment_amount=1000, months=12, annual_rate=Decimal("0.05"))
    assert pv == Decimal("11688.18")


def test_full_termination_gain():
    # Derecognise liability 10000 and ROU 8000, pay 500 penalty.
    result = compute_lifecycle_event(
        event_type="full_termination",
        pre_liability=Decimal("10000"),
        pre_rou=Decimal("8000"),
        termination_penalty=Decimal("500"),
    )
    assert result["post_liability"] == Decimal("0.00")
    assert result["post_rou"] == Decimal("0.00")
    # Gain = 10000 - 8000 - 500.
    assert result["gain_loss"] == Decimal("1500.00")


def test_full_termination_loss_when_rou_exceeds_liability():
    result = compute_lifecycle_event(
        event_type="full_termination",
        pre_liability=Decimal("8000"),
        pre_rou=Decimal("10000"),
    )
    # Loss = 8000 - 10000 = -2000.
    assert result["gain_loss"] == Decimal("-2000.00")


def test_modification_adjusts_rou_by_liability_change_no_pl():
    result = compute_lifecycle_event(
        event_type="modification",
        pre_liability=Decimal("10000"),
        pre_rou=Decimal("8000"),
        new_payment_amount=Decimal("1000"),
        remaining_term_months=12,
        new_incremental_borrowing_rate=Decimal("0.05"),
    )
    assert result["revised_liability"] == Decimal("11688.18")
    assert result["liability_adjustment"] == Decimal("1688.18")
    # ROU moves with the liability; no gain/loss on a straight modification.
    assert result["post_rou"] == Decimal("9688.18")
    assert result["gain_loss"] == Decimal("0.00")


def test_modification_decrease_below_zero_rou_books_gain():
    # A large drop in the liability drives ROU negative -> floored at 0, gain in P&L.
    result = compute_lifecycle_event(
        event_type="modification",
        pre_liability=Decimal("10000"),
        pre_rou=Decimal("5000"),
        new_payment_amount=Decimal("100"),
        remaining_term_months=10,
        new_incremental_borrowing_rate=Decimal("0.05"),
    )
    assert result["post_rou"] == Decimal("0.00")
    # Gain = (10000 - revised) - 5000.
    expected_gain = (Decimal("10000") - result["revised_liability"]) - Decimal("5000")
    assert result["gain_loss"] == expected_gain.quantize(Decimal("0.01"))


def test_partial_termination_proportionate_reduction():
    result = compute_lifecycle_event(
        event_type="partial_termination",
        pre_liability=Decimal("10000"),
        pre_rou=Decimal("8000"),
        remaining_percentage=Decimal("0.6"),
    )
    assert result["post_liability"] == Decimal("6000.00")
    assert result["post_rou"] == Decimal("4800.00")
    # Gain = liability reduction (4000) - ROU reduction (3200).
    assert result["gain_loss"] == Decimal("800.00")


def test_partial_termination_requires_valid_percentage():
    with pytest.raises(LifecycleError):
        compute_lifecycle_event(
            event_type="partial_termination",
            pre_liability=Decimal("10000"),
            pre_rou=Decimal("8000"),
            remaining_percentage=Decimal("1.5"),
        )


def test_invalid_event_type_rejected():
    with pytest.raises(LifecycleError):
        compute_lifecycle_event(
            event_type="bogus", pre_liability=Decimal("1"), pre_rou=Decimal("1")
        )


def test_gain_loss_always_balances_journal():
    # The gain/loss must equal the figure that balances liability + ROU + cash.
    result = compute_lifecycle_event(
        event_type="partial_termination",
        pre_liability=Decimal("10000"),
        pre_rou=Decimal("8000"),
        remaining_percentage=Decimal("0.5"),
        termination_penalty=Decimal("250"),
    )
    net_debit = (
        (Decimal("10000") - result["post_liability"])
        + (result["post_rou"] - Decimal("8000"))
        - Decimal("250")
    )
    assert result["gain_loss"] == net_debit.quantize(Decimal("0.01"))


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def lifecycle_lease(db_session: AsyncSession) -> Lease:
    lease = Lease(
        id=uuid.uuid4(),
        organization_id=None,
        lease_name="Lifecycle Test Lease",
        expiration_year=2028,
        lease_commencement_date=date(2026, 1, 1),
        lease_expiration=date(2028, 1, 1),
        accounting_standard="asc842",
        lease_classification="operating",
        payment_amount=Decimal("1000"),
        payment_frequency="monthly",
        incremental_borrowing_rate=Decimal("0.05"),
        currency="USD",
    )
    db_session.add(lease)
    await db_session.commit()
    await db_session.refresh(lease)
    return lease


# ─── API / GL flow tests ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_viewer_cannot_access_lifecycle(client, viewer_user):
    resp = await client.get("/api/v1/lifecycle/events", headers=auth_headers(viewer_user))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_full_termination_derives_carrying(
    client, accountant_user, lifecycle_lease
):
    headers = auth_headers(accountant_user)
    resp = await client.post(
        "/api/v1/lifecycle/events",
        headers=headers,
        json={
            "lease_id": str(lifecycle_lease.id),
            "event_type": "full_termination",
            "effective_date": "2027-01-01",
            "termination_penalty": "500",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "draft"
    # Pre-event carrying amounts were derived from the lease schedule (~1 year in).
    assert Decimal(body["pre_liability"]) > Decimal("0")
    assert Decimal(body["pre_rou"]) > Decimal("0")
    assert Decimal(body["post_liability"]) == Decimal("0.00")
    assert Decimal(body["post_rou"]) == Decimal("0.00")


@pytest.mark.asyncio
async def test_create_modification_with_explicit_carrying(
    client, accountant_user, lifecycle_lease
):
    headers = auth_headers(accountant_user)
    resp = await client.post(
        "/api/v1/lifecycle/events",
        headers=headers,
        json={
            "lease_id": str(lifecycle_lease.id),
            "event_type": "modification",
            "effective_date": "2027-01-01",
            "pre_liability": "10000",
            "pre_rou": "8000",
            "new_payment_amount": "1000",
            "remaining_term_months": 12,
            "new_incremental_borrowing_rate": "0.05",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert Decimal(body["revised_liability"]) == Decimal("11688.18")
    assert Decimal(body["post_rou"]) == Decimal("9688.18")
    assert Decimal(body["gain_loss"]) == Decimal("0.00")


@pytest.mark.asyncio
async def test_update_recomputes_draft(client, accountant_user, lifecycle_lease):
    headers = auth_headers(accountant_user)
    created = await client.post(
        "/api/v1/lifecycle/events",
        headers=headers,
        json={
            "lease_id": str(lifecycle_lease.id),
            "event_type": "partial_termination",
            "effective_date": "2027-01-01",
            "pre_liability": "10000",
            "pre_rou": "8000",
            "remaining_percentage": "0.6",
        },
    )
    event_id = created.json()["id"]
    resp = await client.patch(
        f"/api/v1/lifecycle/events/{event_id}",
        headers=headers,
        json={"remaining_percentage": "0.5"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert Decimal(body["post_liability"]) == Decimal("5000.00")
    assert Decimal(body["post_rou"]) == Decimal("4000.00")
    assert Decimal(body["gain_loss"]) == Decimal("1000.00")


@pytest.mark.asyncio
async def test_finalize_blocks_further_edits(client, accountant_user, lifecycle_lease):
    headers = auth_headers(accountant_user)
    created = await client.post(
        "/api/v1/lifecycle/events",
        headers=headers,
        json={
            "lease_id": str(lifecycle_lease.id),
            "event_type": "full_termination",
            "effective_date": "2027-01-01",
            "pre_liability": "10000",
            "pre_rou": "8000",
        },
    )
    event_id = created.json()["id"]
    fin = await client.post(
        f"/api/v1/lifecycle/events/{event_id}/finalize", headers=headers
    )
    assert fin.status_code == 200
    assert fin.json()["status"] == "finalized"

    patched = await client.patch(
        f"/api/v1/lifecycle/events/{event_id}",
        headers=headers,
        json={"termination_penalty": "1"},
    )
    assert patched.status_code == 409
    deleted = await client.delete(
        f"/api/v1/lifecycle/events/{event_id}", headers=headers
    )
    assert deleted.status_code == 409


@pytest.mark.asyncio
async def test_post_to_gl_requires_finalized(client, accountant_user, lifecycle_lease):
    headers = auth_headers(accountant_user)
    created = await client.post(
        "/api/v1/lifecycle/events",
        headers=headers,
        json={
            "lease_id": str(lifecycle_lease.id),
            "event_type": "full_termination",
            "effective_date": "2027-01-01",
            "pre_liability": "10000",
            "pre_rou": "8000",
        },
    )
    event_id = created.json()["id"]
    resp = await client.post(
        f"/api/v1/lifecycle/events/{event_id}/post-to-gl", headers=headers
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_to_gl_creates_balanced_entry(
    client, accountant_user, lifecycle_lease
):
    headers = auth_headers(accountant_user)
    created = await client.post(
        "/api/v1/lifecycle/events",
        headers=headers,
        json={
            "lease_id": str(lifecycle_lease.id),
            "event_type": "full_termination",
            "effective_date": "2027-01-01",
            "pre_liability": "10000",
            "pre_rou": "8000",
            "termination_penalty": "500",
        },
    )
    event_id = created.json()["id"]
    await client.post(f"/api/v1/lifecycle/events/{event_id}/finalize", headers=headers)

    resp = await client.post(
        f"/api/v1/lifecycle/events/{event_id}/post-to-gl", headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["posted"] is True
    assert body["journal_entry_id"] is not None
    assert Decimal(body["gain_loss"]) == Decimal("1500.00")

    entries = await client.get(
        "/api/v1/gl/journal-entries?source=lifecycle", headers=headers
    )
    assert entries.status_code == 200
    je = entries.json()
    assert len(je) == 1
    total_debit = sum(Decimal(line["debit"]) for line in je[0]["lines"])
    total_credit = sum(Decimal(line["credit"]) for line in je[0]["lines"])
    assert total_debit == total_credit
    # Liability 10000 derecognised on the debit side.
    assert total_debit == Decimal("10000.00")


@pytest.mark.asyncio
async def test_post_to_gl_idempotent_repost(client, accountant_user, lifecycle_lease):
    headers = auth_headers(accountant_user)
    created = await client.post(
        "/api/v1/lifecycle/events",
        headers=headers,
        json={
            "lease_id": str(lifecycle_lease.id),
            "event_type": "full_termination",
            "effective_date": "2027-01-01",
            "pre_liability": "10000",
            "pre_rou": "8000",
        },
    )
    event_id = created.json()["id"]
    await client.post(f"/api/v1/lifecycle/events/{event_id}/finalize", headers=headers)
    await client.post(f"/api/v1/lifecycle/events/{event_id}/post-to-gl", headers=headers)
    await client.post(f"/api/v1/lifecycle/events/{event_id}/post-to-gl", headers=headers)

    entries = await client.get(
        "/api/v1/gl/journal-entries?source=lifecycle", headers=headers
    )
    # Re-posting replaces rather than duplicates the entry.
    assert len(entries.json()) == 1
