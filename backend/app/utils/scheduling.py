"""Shared scheduling helpers for "fire on a schedule" rule engines.

Both the recurring-ticket engine and (future) report-schedule engine need to
recompute a rule's ``next_run_at`` after it fires. Historically this lived
inline in ``app/tasks/recurring_tickets.py``; it is centralised here so every
schedule-driven rule type computes its cadence the same way.

The vocabulary is intentionally small and shared: ``frequency`` is one of
``daily``/``weekly``/``monthly`` with optional ``day_of_week`` (0=Mon..6=Sun)
and ``day_of_month`` (1-31). Runs are anchored at 08:00 UTC, matching the
existing recurring-ticket behaviour.
"""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta, timezone

# Supported scheduling cadences (shared across rule types).
SCHEDULE_FREQUENCIES = ("daily", "weekly", "monthly")

# Runs are anchored to this hour (UTC) regardless of when a rule last fired.
_RUN_HOUR = 8


def compute_next_run(
    frequency: str,
    day_of_week: int | None = None,
    day_of_month: int | None = None,
    *,
    now: datetime | None = None,
) -> datetime:
    """Compute the next ``next_run_at`` for a schedule-driven rule.

    Behaviour preserved verbatim from the original recurring-ticket logic:

    * runs are anchored at 08:00 (``_RUN_HOUR``) on the target day,
    * ``daily`` → tomorrow,
    * ``weekly`` → the next occurrence of ``day_of_week`` (defaulting to Monday),
      always at least one day ahead (a same-day match rolls to next week),
    * ``monthly`` → ``day_of_month`` (defaulting to the 1st) of next month,
      clamped to the last valid day of that month,
    * any unknown frequency falls back to ``daily``.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    base = now.replace(hour=_RUN_HOUR, minute=0, second=0, microsecond=0)

    if frequency == "daily":
        return base + timedelta(days=1)

    if frequency == "weekly":
        if day_of_week is None:
            day_of_week = 0
        days_ahead = (day_of_week - now.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        return base + timedelta(days=days_ahead)

    if frequency == "monthly":
        if day_of_month is None:
            day_of_month = 1
        # Next month
        if base.month == 12:
            next_month = base.replace(year=base.year + 1, month=1)
        else:
            next_month = base.replace(month=base.month + 1)
        last_day = calendar.monthrange(next_month.year, next_month.month)[1]
        day = min(day_of_month, last_day)
        return next_month.replace(day=day)

    return base + timedelta(days=1)
