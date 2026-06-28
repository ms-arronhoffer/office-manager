"""Tests for the shared rule-scheduling abstraction (Item 3).

Covers the extracted ``compute_next_run`` utility (parity with the original
recurring-ticket logic) and that the rule runner fires recurring-ticket rules
exactly as the old hand-rolled loop did.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.maintenance_ticket import MaintenanceTicket
from app.models.recurring_ticket_rule import RecurringTicketRule
from app.tasks.recurring_tickets import _compute_next_run
from app.tasks.rule_runner import run_due_rules
from app.utils.scheduling import compute_next_run


def test_compute_next_run_daily():
    now = datetime(2026, 6, 28, 9, 30, tzinfo=timezone.utc)
    nxt = compute_next_run("daily", now=now)
    assert nxt == datetime(2026, 6, 29, 8, 0, tzinfo=timezone.utc)


def test_compute_next_run_weekly_rolls_forward_on_same_day():
    # 2026-06-28 is a Sunday (weekday 6); asking for Sunday rolls a full week.
    now = datetime(2026, 6, 28, 9, 0, tzinfo=timezone.utc)
    nxt = compute_next_run("weekly", day_of_week=6, now=now)
    assert nxt == datetime(2026, 7, 5, 8, 0, tzinfo=timezone.utc)


def test_compute_next_run_monthly_clamps_to_last_day():
    # Jan 31 -> Feb has no 31st, clamp to 28 (2026 is not a leap year).
    now = datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc)
    nxt = compute_next_run("monthly", day_of_month=31, now=now)
    assert nxt == datetime(2026, 2, 28, 8, 0, tzinfo=timezone.utc)


def test_compute_next_run_unknown_frequency_defaults_daily():
    now = datetime(2026, 6, 28, 9, 0, tzinfo=timezone.utc)
    assert compute_next_run("bogus", now=now) == compute_next_run("daily", now=now)


def test_recurring_tickets_reexport_is_shared_util():
    assert _compute_next_run is compute_next_run


@pytest.mark.asyncio
async def test_runner_fires_due_ticket_rule(db_session, editor_user, sample_office, sample_category):
    rule = RecurringTicketRule(
        name="Monthly filter check",
        subject="Replace HVAC filters",
        description="Routine",
        priority="medium",
        category_id=sample_category.id,
        office_id=sample_office.id,
        frequency="monthly",
        day_of_month=1,
        is_active=True,
        created_by_id=editor_user.id,
        next_run_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db_session.add(rule)
    await db_session.commit()
    rule_id = rule.id

    fired = await run_due_rules("ticket")
    assert fired == 1

    # A ticket was created from the rule's template.
    result = await db_session.execute(
        select(MaintenanceTicket).where(MaintenanceTicket.subject == "Replace HVAC filters")
    )
    tickets = result.scalars().all()
    assert len(tickets) == 1
    assert tickets[0].office_id == sample_office.id
    assert tickets[0].status == "open"

    # The rule was rescheduled into the future and stamped with last_run_at.
    refreshed = await db_session.get(RecurringTicketRule, rule_id)
    await db_session.refresh(refreshed)
    assert refreshed.last_run_at is not None
    assert refreshed.next_run_at > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_runner_skips_inactive_and_future_rules(db_session, sample_office, sample_category):
    future = RecurringTicketRule(
        name="Future",
        subject="Future ticket",
        priority="low",
        category_id=sample_category.id,
        office_id=sample_office.id,
        frequency="daily",
        is_active=True,
        next_run_at=datetime.now(timezone.utc) + timedelta(days=1),
    )
    inactive = RecurringTicketRule(
        name="Inactive",
        subject="Inactive ticket",
        priority="low",
        category_id=sample_category.id,
        office_id=sample_office.id,
        frequency="daily",
        is_active=False,
        next_run_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db_session.add_all([future, inactive])
    await db_session.commit()

    fired = await run_due_rules("ticket")
    assert fired == 0

    result = await db_session.execute(select(MaintenanceTicket))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_runner_unknown_action_type_is_noop():
    assert await run_due_rules("does-not-exist") == 0
