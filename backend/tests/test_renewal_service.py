"""Tests for lease deadline automation: notice dates, urgency and option exercise."""

import uuid
from datetime import date, timedelta

import pytest

from app.models.lease import Lease
from app.models.lease_option import LeaseOption
from app.models.lease_renewal import LeaseRenewal
from app.services import renewal_service


def _lease(expiration=None, notice_date=None, notice_days=None) -> Lease:
    return Lease(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        lease_name="Harbor View Tower - Suite 400",
        lease_expiration=expiration,
        lease_notice_date=notice_date,
        notice_period_days=notice_days,
        expiration_year=(expiration.year if expiration else 2027),
    )


# ─── Notice date derivation ──────────────────────────────────────────────────

def test_explicit_notice_date_wins():
    lease = _lease(
        expiration=date(2027, 5, 4),
        notice_date=date(2026, 11, 4),
        notice_days=90,
    )
    assert renewal_service.notice_due_date(lease) == date(2026, 11, 4)


def test_notice_date_derived_from_period():
    lease = _lease(expiration=date(2027, 5, 4), notice_days=90)
    assert renewal_service.notice_due_date(lease) == date(2027, 2, 3)


def test_notice_date_unknown_without_period_or_date():
    assert renewal_service.notice_due_date(_lease(expiration=date(2027, 5, 4))) is None


# ─── Urgency banding ─────────────────────────────────────────────────────────

def test_days_remaining_counts_down_and_goes_negative():
    today = date(2026, 8, 8)
    assert renewal_service.days_remaining(date(2026, 8, 18), today) == 10
    assert renewal_service.days_remaining(date(2026, 8, 1), today) == -7


@pytest.mark.parametrize(
    "days,expected",
    [
        (-1, "overdue"),
        (-45, "overdue"),
        (0, "critical"),
        (14, "critical"),
        (15, "urgent"),
        (45, "urgent"),
        (46, "upcoming"),
        (None, "unscheduled"),
    ],
)
def test_urgency_bands(days, expected):
    assert renewal_service.urgency(days) == expected


# ─── Option exercise ─────────────────────────────────────────────────────────

def _option(status="open", rent="5200", months=60) -> LeaseOption:
    return LeaseOption(
        id=uuid.uuid4(),
        lease_id=uuid.uuid4(),
        option_type="renewal",
        exercise_window_start=date(2026, 1, 1),
        exercise_window_end=date(2026, 12, 31),
        new_rent_amount=rent,
        new_term_months=months,
        status=status,
    )


def test_exercising_an_option_produces_an_owned_renewal():
    option = _option()
    user_id = uuid.uuid4()
    lease_id = uuid.uuid4()

    renewal = renewal_service.exercise_option(
        option, user_id=user_id, lease_id=lease_id
    )

    assert isinstance(renewal, LeaseRenewal)
    assert renewal.lease_id == lease_id
    assert renewal.owner_id == user_id
    assert renewal.status == "in_progress"
    assert option.status == "exercised"
    assert option.exercised_by_id == user_id
    assert option.exercised_at is not None


def test_an_option_cannot_be_exercised_twice():
    option = _option(status="exercised")
    with pytest.raises(ValueError, match="can no longer be exercised"):
        renewal_service.exercise_option(
            option, user_id=uuid.uuid4(), lease_id=uuid.uuid4()
        )


# ─── Notice evidence ─────────────────────────────────────────────────────────

def test_recording_notice_captures_delivery_evidence():
    renewal = LeaseRenewal(id=uuid.uuid4(), lease_id=uuid.uuid4(), status="in_progress")

    renewal_service.record_notice(
        renewal, method="certified_mail", reference="RA123456789US"
    )

    assert renewal.notice_sent_at is not None
    assert renewal.notice_method == "certified_mail"
    assert renewal.notice_reference == "RA123456789US"


# ─── Pipeline shaping ────────────────────────────────────────────────────────

def test_pipeline_entry_reports_not_started_without_a_renewal():
    today = date(2026, 8, 8)
    # Notice falls 25 days out, which is inside the "urgent" band.
    lease = _lease(expiration=date(2026, 12, 1), notice_days=90)

    entry = renewal_service.pipeline_entry(lease, None, today)

    assert entry["stage"] == "not_started"
    assert entry["notice_due_date"] == date(2026, 9, 2)
    assert entry["days_until_notice_due"] == 25
    assert entry["urgency"] == "urgent"
    assert entry["renewal_id"] is None


def test_pipeline_entry_urgency_relaxes_for_distant_deadlines():
    today = date(2026, 8, 8)
    # Notice 55 days out is real work, but not yet urgent.
    lease = _lease(expiration=date(2026, 12, 1), notice_days=60)

    entry = renewal_service.pipeline_entry(lease, None, today)

    assert entry["notice_due_date"] == date(2026, 10, 2)
    assert entry["urgency"] == "upcoming"


def test_pipeline_entry_advances_with_the_renewal():
    today = date(2026, 8, 8)
    lease = _lease(expiration=date(2026, 12, 1), notice_days=60)
    renewal = LeaseRenewal(
        id=uuid.uuid4(),
        lease_id=lease.id,
        status="in_progress",
        notice_due_date=date(2026, 10, 2),
    )

    assert renewal_service.pipeline_entry(lease, renewal, today)["stage"] == "open"

    renewal_service.record_notice(renewal)
    assert renewal_service.pipeline_entry(lease, renewal, today)["stage"] == "notice_served"


def test_pipeline_entry_flags_an_overdue_notice():
    today = date(2026, 8, 8)
    lease = _lease(expiration=date(2026, 9, 1), notice_days=60)

    entry = renewal_service.pipeline_entry(lease, None, today)

    assert entry["days_until_notice_due"] < 0
    assert entry["urgency"] == "overdue"


def test_lead_window_default_is_a_full_quarter_plus():
    """Renewal work must start well before the legal deadline."""
    assert renewal_service.DEFAULT_LEAD_DAYS >= 90
    horizon = date(2026, 8, 8) + timedelta(days=renewal_service.DEFAULT_LEAD_DAYS)
    assert horizon > date(2026, 11, 1)
