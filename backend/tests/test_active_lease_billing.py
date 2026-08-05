"""Database tests for monthly active-lease billing evidence."""
from datetime import datetime, timezone
import uuid

import pytest

from app.models.organization import Organization
from app.services import metering_service as metering


@pytest.mark.asyncio
async def test_active_lease_counts_once_per_month_and_survives_status_change(db_session):
    org = Organization(name="Metered Org", slug=f"metered-{uuid.uuid4().hex}", plan="pro")
    db_session.add(org)
    await db_session.flush()
    lease_id = uuid.uuid4()
    when = datetime(2026, 8, 2, 12, tzinfo=timezone.utc)

    await metering.record_active_lease_month(
        db_session,
        organization_id=org.id,
        lease_type="commercial",
        lease_id=lease_id,
        status="Active",
        when=when,
    )
    await metering.record_active_lease_month(
        db_session,
        organization_id=org.id,
        lease_type="commercial",
        lease_id=lease_id,
        status="active",
        when=when,
    )
    await metering.record_active_lease_month(
        db_session,
        organization_id=org.id,
        lease_type="commercial",
        lease_id=lease_id,
        status="terminated",
        when=when,
    )
    await db_session.commit()

    breakdown = await metering.count_billable_units(
        db_session, org.id, period="2026-08"
    )
    assert breakdown == {"commercial": 1, "residential": 0}
    assert metering.snapshot_payload(breakdown)["billed_leases"] == 0


@pytest.mark.asyncio
async def test_same_lease_can_count_in_a_later_month(db_session):
    org = Organization(name="Carry Org", slug=f"carry-{uuid.uuid4().hex}", plan="pro")
    db_session.add(org)
    await db_session.flush()
    lease_id = uuid.uuid4()

    for moment in (
        datetime(2026, 8, 31, tzinfo=timezone.utc),
        datetime(2026, 9, 1, tzinfo=timezone.utc),
    ):
        await metering.record_active_lease_month(
            db_session,
            organization_id=org.id,
            lease_type="residential",
            lease_id=lease_id,
            status="active",
            when=moment,
        )
    await db_session.commit()

    august = await metering.count_billable_units(db_session, org.id, period="2026-08")
    september = await metering.count_billable_units(db_session, org.id, period="2026-09")
    assert august["residential"] == 1
    assert september["residential"] == 1


@pytest.mark.asyncio
async def test_unset_status_records_as_active_usage(db_session):
    org = Organization(name="Unset Org", slug=f"unset-{uuid.uuid4().hex}", plan="pro")
    db_session.add(org)
    await db_session.flush()

    await metering.record_active_lease_month(
        db_session,
        organization_id=org.id,
        lease_type="commercial",
        lease_id=uuid.uuid4(),
        status=None,
        when=datetime(2026, 8, 5, tzinfo=timezone.utc),
    )
    await db_session.commit()

    breakdown = await metering.count_billable_units(db_session, org.id, period="2026-08")
    assert breakdown["commercial"] == 1
