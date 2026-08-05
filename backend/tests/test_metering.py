"""Tests for billable-unit metering (per-unit banded billing).

The unit-count arithmetic and period/floor rules are pure functions, so these
run without a database.
"""

from datetime import datetime, timezone

from app.services.metering_service import (
    BASE_FEE_CENTS,
    BILLABLE_UNIT_FLOOR,
    CATEGORIES,
    INCLUDED_LEASES,
    PER_ADDITIONAL_LEASE_CENTS,
    billable_quantity,
    billed_leases,
    build_breakdown,
    estimated_monthly_charge_cents,
    is_billable_active_status,
    period_month,
    snapshot_payload,
    total_units,
)


def test_breakdown_sums_commercial_and_residential_leases():
    breakdown = build_breakdown(commercial=4, residential=9)
    assert breakdown == {"commercial": 4, "residential": 9}
    assert total_units(breakdown) == 13


def test_breakdown_defaults_missing_categories_to_zero():
    breakdown = build_breakdown(residential=3)
    assert breakdown["commercial"] == 0
    assert total_units(breakdown) == 3


def test_breakdown_clamps_negative_counts():
    breakdown = build_breakdown(commercial=-5, residential=2)
    assert breakdown == {"commercial": 0, "residential": 2}
    assert total_units(breakdown) == 2


def test_total_units_ignores_unknown_keys():
    assert total_units({"commercial": 2, "residential": 1, "offices": 999}) == 3


def test_empty_org_has_no_billable_units():
    assert total_units(build_breakdown()) == 0


def test_quantity_raised_to_three_included_leases():
    assert INCLUDED_LEASES == 3
    assert billable_quantity(0) == BILLABLE_UNIT_FLOOR
    assert billable_quantity(3) == BILLABLE_UNIT_FLOOR


def test_quantity_tracks_units_above_the_floor():
    assert billable_quantity(BILLABLE_UNIT_FLOOR + 1) == BILLABLE_UNIT_FLOOR + 1
    assert billable_quantity(842) == 842


def test_quantity_honours_an_explicit_floor():
    assert billable_quantity(5, floor=2) == 5
    assert billable_quantity(1, floor=25) == 25


def test_period_month_formats_as_year_month():
    when = datetime(2026, 8, 1, 12, 30, tzinfo=timezone.utc)
    assert period_month(when) == "2026-08"


def test_period_month_normalises_naive_datetimes():
    assert period_month(datetime(2026, 12, 31, 23, 0)) == "2026-12"


def test_period_month_converts_to_utc():
    from datetime import timedelta

    # 2026-09-01 00:30 at UTC+2 is still 2026-08-31 in UTC.
    local = datetime(2026, 9, 1, 0, 30, tzinfo=timezone(timedelta(hours=2)))
    assert period_month(local) == "2026-08"


def test_snapshot_payload_reports_units_and_billed_quantity():
    payload = snapshot_payload(build_breakdown(commercial=1, residential=1))
    assert payload["billable_units"] == 2
    assert payload["billable_quantity"] == BILLABLE_UNIT_FLOOR
    assert payload["floor"] == BILLABLE_UNIT_FLOOR
    assert payload["included_leases"] == 3
    assert payload["billed_leases"] == 0
    assert payload["estimated_monthly_charge_cents"] == 3900
    assert set(payload["breakdown"]) == set(CATEGORIES)


def test_snapshot_payload_for_a_large_customer():
    payload = snapshot_payload(
        build_breakdown(commercial=120, residential=380)
    )
    assert payload["billable_units"] == 500
    assert payload["billable_quantity"] == 500
    assert payload["billed_leases"] == 497


def test_snapshot_payload_always_lists_every_category():
    payload = snapshot_payload({"residential": 4})
    assert payload["breakdown"] == {
        "commercial": 0,
        "residential": 4,
    }


def test_base_fee_and_per_lease_formula():
    assert BASE_FEE_CENTS == 3900
    assert PER_ADDITIONAL_LEASE_CENTS == 400
    assert billed_leases(0) == 0
    assert billed_leases(3) == 0
    assert billed_leases(4) == 1
    assert billed_leases(10) == 7
    assert estimated_monthly_charge_cents(0) == 3900
    assert estimated_monthly_charge_cents(3) == 3900
    assert estimated_monthly_charge_cents(4) == 4300
    assert estimated_monthly_charge_cents(10) == 6700


def test_only_exact_active_status_is_billable():
    assert is_billable_active_status("Active") is True
    assert is_billable_active_status(" active ") is True
    assert is_billable_active_status(None) is True
    assert is_billable_active_status("") is True
    assert is_billable_active_status("   ") is True
    assert is_billable_active_status("pending") is False
