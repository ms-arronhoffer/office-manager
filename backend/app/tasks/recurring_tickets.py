"""APScheduler task: auto-create maintenance tickets for active recurring rules.

The scheduling logic now lives in the shared rule-runner abstraction
(:mod:`app.tasks.rule_runner` + :mod:`app.tasks.rule_evaluator`); this module
keeps the original scheduler entry point and a backwards-compatible
``_compute_next_run`` alias that re-exports the shared utility.
"""

import logging

from app.tasks.rule_runner import run_due_rules
from app.utils.scheduling import compute_next_run as _compute_next_run  # noqa: F401  (back-compat re-export)

logger = logging.getLogger(__name__)


async def create_recurring_tickets() -> None:
    """Query active rules due to run and create a MaintenanceTicket for each."""
    await run_due_rules("ticket")
