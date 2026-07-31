"""Historical CAM schedule import.

Covers the invariant the feature exists to protect: importing years of prior
lease financials populates the lease's CAM schedule as reference data and never
changes the active lease's own financial terms. Only the explicit promote
action does that.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lease import Lease, LeaseCamEntry
from app.models.organization import Organization
from app.models.user import User
from app.auth.password import hash_password
from app.services import ai_service, cam_schedule_service
from tests.conftest import auth_headers


# ─── Row normalization ───────────────────────────────────────────────────────

def test_normalize_accepts_aliases_and_formatting():
    rows = cam_schedule_service.normalize_history_rows(
        [
            {
                "Lease Year": "2019",
                "Base Rent": "$12,500.50",
                "Rent Frequency": "per month",
                "CAM": "1,200",
                "Escalation %": "3%",
                "True Up": "(450.00)",
                "Confidence": "85",
                "Comment": " prior lease ",
            }
        ]
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["year"] == 2019
    assert row["base_rent_amount"] == Decimal("12500.50")
    assert row["base_rent_frequency"] == "monthly"
    assert row["amount"] == Decimal("1200")
    assert row["base_rent_escalation_rate"] == Decimal("0.03")
    # Accounting-style parentheses mean a credit back to the tenant.
    assert row["reconciliation_true_up"] == Decimal("-450.00")
    assert row["extraction_confidence"] == Decimal("0.850")
    assert row["notes"] == "prior lease"
    # An amount is present, so this is a fixed row, not a percent-increase one.
    assert row["charge_type"] == "fixed"


def test_normalize_infers_year_and_percent_increase_rows():
    rows = cam_schedule_service.normalize_history_rows(
        [
            {"period_start": "2020-07-01", "period_end": "2021-06-30",
             "cam_percent_increase": 0.025},
            {"year": "not a year"},
            "junk",
        ]
    )
    assert len(rows) == 1
    assert rows[0]["year"] == 2020
    assert rows[0]["charge_type"] == "percent_increase"
    assert rows[0]["percent_increase"] == Decimal("0.025")
    assert rows[0]["period_end"] == date(2021, 6, 30)


def test_normalize_merges_duplicate_years_and_sorts():
    rows = cam_schedule_service.normalize_history_rows(
        [
            {"year": 2021, "cam_amount": 1000},
            {"year": 2020, "base_rent": 5000},
            {"year": 2021, "base_rent": 6000, "cam_amount": 9999},
        ]
    )
    assert [r["year"] for r in rows] == [2020, 2021]
    merged = rows[1]
    # First non-empty value wins, matching the AI segment-merge rule.
    assert merged["amount"] == Decimal("1000")
    assert merged["base_rent_amount"] == Decimal("6000")


def test_normalize_handles_malformed_model_output():
    assert cam_schedule_service.normalize_history_rows(None) == []
    assert cam_schedule_service.normalize_history_rows({"periods": []}) == []
    assert cam_schedule_service.normalize_history_rows(["", 3, None]) == []


# ─── Segment merge (large documents split across AI calls) ───────────────────

def test_segment_merge_unions_lists_by_year():
    merged = ai_service._merge_segment_results(
        [
            {"periods": [{"year": 2019, "base_rent": 1000},
                         {"year": 2020, "base_rent": 1100}]},
            {"periods": [{"year": 2020, "cam_amount": 500},
                         {"year": 2021, "base_rent": 1200}]},
        ]
    )
    years = [row["year"] for row in merged["periods"]]
    assert years == [2019, 2020, 2021]
    # The later segment filled a gap on the year the segments shared, rather
    # than replacing the whole list (last-write-wins).
    row_2020 = next(r for r in merged["periods"] if r["year"] == 2020)
    assert row_2020["base_rent"] == 1100
    assert row_2020["cam_amount"] == 500


# ─── CSV parsing ─────────────────────────────────────────────────────────────

def test_parse_history_csv_maps_headers_and_warns():
    csv_text = (
        "Year,Base Rent,Rent Frequency,CAM,Escalation %,Mystery\n"
        "2018,10000,annually,1500,2,foo\n"
        "2019,10200,annually,1560,2,bar\n"
    )
    rows, warnings = cam_schedule_service.parse_history_csv(csv_text.encode("utf-8"))
    assert [r["year"] for r in rows] == [2018, 2019]
    assert rows[0]["base_rent_frequency"] == "annually"
    assert rows[0]["base_rent_escalation_rate"] == Decimal("0.02")
    assert any("Mystery" in w for w in warnings)


def test_parse_history_csv_rejects_unusable_input():
    with pytest.raises(cam_schedule_service.CamImportError):
        cam_schedule_service.parse_history_csv(b"")
    with pytest.raises(cam_schedule_service.CamImportError):
        cam_schedule_service.parse_history_csv(b"a,b\n1,2\n")


# ─── Escalation chain isolation ──────────────────────────────────────────────

def _entry(year, *, charge_type="fixed", amount=None, percent=None, status="current"):
    return LeaseCamEntry(
        id=uuid.uuid4(),
        lease_id=uuid.uuid4(),
        year=year,
        charge_type=charge_type,
        amount=Decimal(str(amount)) if amount is not None else None,
        percent_increase=Decimal(str(percent)) if percent is not None else None,
        period_status=status,
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


def test_resolve_schedule_keeps_historical_rows_out_of_the_active_chain():
    historical_2019 = _entry(2019, amount=1000, status="historical")
    historical_2020 = _entry(2020, charge_type="percent_increase", percent="0.10",
                             status="historical")
    current_2026 = _entry(2026, amount=5000, status="current")
    projected_2027 = _entry(2027, charge_type="percent_increase", percent="0.03",
                            status="projected")

    resolved = cam_schedule_service.resolve_schedule(
        [projected_2027, historical_2020, current_2026, historical_2019]
    )
    assert resolved[historical_2019.id] == Decimal("1000")
    # Chains off the historical 2019 row, not off anything in the active group.
    assert resolved[historical_2020.id] == Decimal("1100.00")
    assert resolved[current_2026.id] == Decimal("5000")
    # The active chain starts at the current row, untouched by eight years of
    # imported history.
    assert resolved[projected_2027.id] == Decimal("5150.00")


def test_resolve_schedule_returns_none_without_a_fixed_starting_point():
    orphan = _entry(2020, charge_type="percent_increase", percent="0.03")
    assert cam_schedule_service.resolve_schedule([orphan])[orphan.id] is None


def test_derive_period_status():
    today = date(2026, 6, 1)
    assert cam_schedule_service.derive_period_status(2019, today=today) == "historical"
    assert cam_schedule_service.derive_period_status(2026, today=today) == "current"
    assert cam_schedule_service.derive_period_status(2030, today=today) == "projected"


# ─── API fixtures ────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def history_lease(db_session: AsyncSession) -> Lease:
    """An active lease running 2025-2030 with live financial terms set."""
    lease = Lease(
        id=uuid.uuid4(),
        organization_id=None,
        lease_name="History Test Lease",
        expiration_year=2030,
        lease_commencement_date=date(2025, 1, 1),
        lease_expiration=date(2030, 12, 31),
        currency="USD",
        payment_amount=Decimal("9000.00"),
        payment_frequency="monthly",
        annual_escalation_rate=Decimal("0.030000"),
    )
    db_session.add(lease)
    await db_session.commit()
    await db_session.refresh(lease)
    return lease


def _history_rows(*years: int) -> list[dict]:
    return [
        {
            "year": year,
            "base_rent_amount": 5000 + (year - 2017) * 100,
            "base_rent_frequency": "monthly",
            "amount": 1000 + (year - 2017) * 50,
            "extraction_confidence": 0.9,
        }
        for year in years
    ]


async def _import(client, user, lease, rows, **overrides):
    payload = {"rows": rows, "mode": "skip_existing", "period_status": "historical"}
    payload.update(overrides)
    return await client.post(
        f"/api/v1/leases/{lease.id}/cam-entries/import",
        headers=auth_headers(user),
        json=payload,
    )


# ─── Import behaviour ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_import_creates_historical_rows(client, admin_user, history_lease):
    resp = await _import(client, admin_user, history_lease, _history_rows(2018, 2019, 2020))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["created"] == 3
    assert body["conflicts"] == 0
    assert {r["status"] for r in body["results"]} == {"created"}

    listing = await client.get(
        f"/api/v1/leases/{history_lease.id}/cam-entries",
        headers=auth_headers(admin_user),
    )
    entries = listing.json()
    assert len(entries) == 3
    assert all(e["period_status"] == "historical" for e in entries)
    assert all(e["source"] == "ai_import" for e in entries)
    assert all(e["import_batch_id"] == body["import_batch_id"] for e in entries)
    assert entries[0]["effective_amount"] is not None


@pytest.mark.asyncio
async def test_reimport_is_idempotent_then_overwrites(client, admin_user, history_lease):
    first = await _import(client, admin_user, history_lease, _history_rows(2018, 2019))
    assert first.json()["created"] == 2

    again = await _import(client, admin_user, history_lease, _history_rows(2018, 2019))
    body = again.json()
    assert body["created"] == 0 and body["skipped"] == 2
    assert {r["status"] for r in body["results"]} == {"skipped"}

    changed = [dict(row, amount=4242) for row in _history_rows(2018, 2019)]
    overwrite = await _import(
        client, admin_user, history_lease, changed, mode="overwrite"
    )
    assert overwrite.json()["updated"] == 2

    listing = await client.get(
        f"/api/v1/leases/{history_lease.id}/cam-entries",
        headers=auth_headers(admin_user),
    )
    entries = listing.json()
    # Still two rows for the two years, now carrying the corrected amount.
    assert len(entries) == 2
    assert all(Decimal(e["amount"]) == Decimal("4242.00") for e in entries)


@pytest.mark.asyncio
async def test_append_mode_adds_a_second_row(client, admin_user, history_lease):
    await _import(client, admin_user, history_lease, _history_rows(2018))
    resp = await _import(
        client, admin_user, history_lease, _history_rows(2018), mode="append"
    )
    assert resp.json()["created"] == 1
    listing = await client.get(
        f"/api/v1/leases/{history_lease.id}/cam-entries",
        headers=auth_headers(admin_user),
    )
    assert len(listing.json()) == 2


@pytest.mark.asyncio
async def test_rows_overlapping_the_active_term_are_conflicts(
    client, admin_user, history_lease
):
    # 2026 falls inside the active lease term (2025-2030).
    resp = await _import(client, admin_user, history_lease, _history_rows(2019, 2026))
    body = resp.json()
    assert body["created"] == 1
    assert body["conflicts"] == 1
    conflict = next(r for r in body["results"] if r["status"] == "conflict")
    assert conflict["year"] == 2026
    assert conflict["entry_id"] is None

    override = await _import(
        client,
        admin_user,
        history_lease,
        _history_rows(2026),
        allow_active_period_overlap=True,
    )
    assert override.json()["created"] == 1


@pytest.mark.asyncio
async def test_import_batch_can_be_reverted(client, admin_user, history_lease):
    first = await _import(client, admin_user, history_lease, _history_rows(2018))
    second = await _import(client, admin_user, history_lease, _history_rows(2019))
    bad_batch = second.json()["import_batch_id"]

    resp = await client.delete(
        f"/api/v1/leases/{history_lease.id}/cam-entries/import/{bad_batch}",
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1

    listing = await client.get(
        f"/api/v1/leases/{history_lease.id}/cam-entries",
        headers=auth_headers(admin_user),
    )
    remaining = listing.json()
    assert [e["year"] for e in remaining] == [2018]
    assert remaining[0]["import_batch_id"] == first.json()["import_batch_id"]

    missing = await client.delete(
        f"/api/v1/leases/{history_lease.id}/cam-entries/import/{uuid.uuid4()}",
        headers=auth_headers(admin_user),
    )
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_import_rejects_empty_and_oversized_batches(
    client, admin_user, history_lease
):
    empty = await _import(client, admin_user, history_lease, [])
    assert empty.status_code == 400

    too_many = _history_rows(*range(1900, 1900 + cam_schedule_service.MAX_HISTORY_ROWS + 5))
    resp = await _import(client, admin_user, history_lease, too_many)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_viewer_cannot_import_history(client, viewer_user, history_lease):
    resp = await _import(client, viewer_user, history_lease, _history_rows(2018))
    assert resp.status_code == 403


# ─── The core invariant ──────────────────────────────────────────────────────

_LEASE_FINANCIAL_COLUMNS = (
    "payment_amount",
    "payment_frequency",
    "annual_escalation_rate",
    "incremental_borrowing_rate",
    "lease_incentives",
    "initial_direct_costs",
    "prepaid_rent",
)


def _financial_snapshot(lease: Lease) -> dict:
    return {name: getattr(lease, name) for name in _LEASE_FINANCIAL_COLUMNS}


@pytest.mark.asyncio
async def test_import_never_changes_lease_financials(
    client, admin_user, history_lease, db_session
):
    lease_id = history_lease.id
    before = _financial_snapshot(history_lease)
    resp = await _import(
        client,
        admin_user,
        history_lease,
        _history_rows(2018, 2019, 2020, 2021, 2022, 2023, 2024),
    )
    assert resp.json()["created"] == 7

    db_session.expire_all()
    lease = (
        await db_session.execute(select(Lease).where(Lease.id == lease_id))
    ).scalar_one()
    assert _financial_snapshot(lease) == before


@pytest.mark.asyncio
async def test_import_rejects_apply_to_lease(client, admin_user, history_lease):
    resp = await _import(
        client, admin_user, history_lease, _history_rows(2018), apply_to_lease=True
    )
    assert resp.status_code == 400
    assert "promote" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_promote_is_the_only_path_to_current_terms(
    client, admin_user, history_lease, db_session
):
    lease_id = history_lease.id
    await _import(client, admin_user, history_lease, _history_rows(2018))
    listing = await client.get(
        f"/api/v1/leases/{lease_id}/cam-entries",
        headers=auth_headers(admin_user),
    )
    entry_id = listing.json()[0]["id"]

    resp = await client.post(
        f"/api/v1/leases/{lease_id}/cam-entries/{entry_id}/promote",
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 200, resp.text
    assert Decimal(resp.json()["payment_amount"]) == Decimal("5100.00")

    db_session.expire_all()
    lease = (
        await db_session.execute(select(Lease).where(Lease.id == lease_id))
    ).scalar_one()
    assert lease.payment_amount == Decimal("5100.00")
    assert lease.payment_frequency == "monthly"


@pytest.mark.asyncio
async def test_promote_rejects_a_row_with_nothing_to_promote(
    client, admin_user, history_lease
):
    created = await client.post(
        f"/api/v1/leases/{history_lease.id}/cam-entries",
        headers=auth_headers(admin_user),
        json={"year": 2027, "charge_type": "fixed", "amount": "1500"},
    )
    entry_id = created.json()["id"]
    resp = await client.post(
        f"/api/v1/leases/{history_lease.id}/cam-entries/{entry_id}/promote",
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 400


# ─── Tenant isolation ────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def other_org_admin(db_session: AsyncSession) -> User:
    org = Organization(id=uuid.uuid4(), name="Other Org", slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        email=f"other-admin-{uuid.uuid4().hex[:8]}@test.com",
        display_name="Other Admin",
        password_hash=hash_password("OtherAdmin123!"),
        auth_provider="internal",
        role="admin",
        is_active=True,
        organization_id=org.id,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_import_is_org_scoped(client, other_org_admin, history_lease):
    """A lease from another organization is invisible, so nothing can be imported."""
    resp = await _import(client, other_org_admin, history_lease, _history_rows(2018))
    assert resp.status_code == 404

    csv_resp = await client.post(
        f"/api/v1/leases/{history_lease.id}/cam-entries/parse-csv",
        headers=auth_headers(other_org_admin),
        files={"file": ("history.csv", b"year,cam\n2018,100\n", "text/csv")},
    )
    assert csv_resp.status_code == 404

    promote = await client.post(
        f"/api/v1/leases/{history_lease.id}/cam-entries/{uuid.uuid4()}/promote",
        headers=auth_headers(other_org_admin),
    )
    assert promote.status_code == 404


# ─── CSV staging endpoint ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_parse_csv_stages_rows_without_writing(
    client, admin_user, history_lease, db_session
):
    csv_bytes = b"Year,Base Rent,CAM\n2018,10000,1500\n2019,10200,1560\n"
    resp = await client.post(
        f"/api/v1/leases/{history_lease.id}/cam-entries/parse-csv",
        headers=auth_headers(admin_user),
        files={"file": ("history.csv", csv_bytes, "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [row["year"] for row in body["periods"]] == [2018, 2019]

    rows = (
        await db_session.execute(
            select(LeaseCamEntry).where(LeaseCamEntry.lease_id == history_lease.id)
        )
    ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_parse_csv_reports_a_bad_file(client, admin_user, history_lease):
    resp = await client.post(
        f"/api/v1/leases/{history_lease.id}/cam-entries/parse-csv",
        headers=auth_headers(admin_user),
        files={"file": ("history.csv", b"alpha,beta\n1,2\n", "text/csv")},
    )
    assert resp.status_code == 400


# ─── Reconciliation comparatives ─────────────────────────────────────────────

def test_historical_comparatives_only_uses_historical_rows():
    historical = _entry(2019, amount=1200, status="historical")
    historical.base_rent_amount = Decimal("5000")
    current = _entry(2026, amount=1800, status="current")

    comparatives = cam_schedule_service.historical_comparatives([current, historical])
    assert [c["year"] for c in comparatives] == [2019]
    assert comparatives[0]["cam_amount"] == Decimal("1200")
    assert comparatives[0]["base_rent_amount"] == Decimal("5000")
    # Empty fields are dropped to keep the prompt payload compact.
    assert "reconciliation_true_up" not in comparatives[0]
