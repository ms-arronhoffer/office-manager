"""Shared scheduling abstraction for "fire on a schedule" rule engines.

The codebase has two independent schedule-driven rule engines: recurring
maintenance tickets and email reminder rules. They share the same three
concerns — *find the rules that are due*, *fire each one*, and *reschedule it
afterwards* — even though one produces tickets and the other produces emails.

:class:`RuleEvaluator` captures that contract so a single runner
(:mod:`app.tasks.rule_runner`) can dispatch any number of rule types without
re-implementing the due-query / fire / reschedule loop. New rule types (e.g. a
COI-expiration evaluator, or scheduled reports) plug in by subclassing this and
registering with the runner.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.maintenance_ticket import MaintenanceTicket
from app.models.recurring_ticket_rule import RecurringTicketRule
from app.utils.scheduling import compute_next_run

logger = logging.getLogger(__name__)


class RuleEvaluator:
    """Abstract base describing one schedule-driven rule type.

    Subclasses implement the three shared operations. The runner owns the
    session and commit; an evaluator should only stage ORM changes (``db.add``
    / attribute mutation) and must isolate per-rule failures so one bad rule
    doesn't abort the batch.
    """

    #: Stable key used by the runner's registry (e.g. ``"ticket"``, ``"email"``).
    action_type: str = ""

    async def due_query(self, db: AsyncSession, now: datetime) -> Sequence[Any]:
        """Return the rules that are due to fire at ``now``."""
        raise NotImplementedError

    async def fire(self, db: AsyncSession, rule: Any, now: datetime) -> None:
        """Perform the rule's action (create a ticket, send email, …)."""
        raise NotImplementedError

    def reschedule(self, rule: Any, now: datetime) -> None:
        """Advance the rule's bookkeeping so it fires again on schedule."""
        raise NotImplementedError


class RecurringTicketEvaluator(RuleEvaluator):
    """Evaluator that creates a :class:`MaintenanceTicket` per due rule.

    This is a faithful extraction of the original ``create_recurring_tickets``
    loop: it selects active rules whose ``next_run_at`` has passed, creates one
    ticket per rule (skipping rules missing required FKs), and advances
    ``last_run_at`` / ``next_run_at`` via the shared scheduling util.
    """

    action_type = "ticket"

    async def due_query(self, db: AsyncSession, now: datetime) -> Sequence[RecurringTicketRule]:
        result = await db.execute(
            select(RecurringTicketRule)
            .options(
                joinedload(RecurringTicketRule.category),
                joinedload(RecurringTicketRule.office),
                joinedload(RecurringTicketRule.assigned_to),
            )
            .where(
                RecurringTicketRule.is_active.is_(True),
                RecurringTicketRule.next_run_at <= now,
            )
        )
        return result.scalars().unique().all()

    async def fire(self, db: AsyncSession, rule: RecurringTicketRule, now: datetime) -> None:
        # Validate required FK fields exist; still reschedule so a misconfigured
        # rule doesn't get stuck re-selected every run.
        if not rule.category_id or not rule.office_id:
            logger.warning(
                "Recurring rule %s (%s) missing category_id or office_id — skipping",
                rule.id,
                rule.name,
            )
            self.reschedule(rule, now)
            return

        ticket = MaintenanceTicket(
            subject=rule.subject,
            description=rule.description or "",
            priority=rule.priority,
            status="open",
            category_id=rule.category_id,
            office_id=rule.office_id,
            assigned_to_id=rule.assigned_to_id,
            created_by_id=rule.created_by_id,
        )
        db.add(ticket)

        rule.last_run_at = now
        self.reschedule(rule, now)

        logger.info(
            "Created recurring ticket for rule %s (%s), next run: %s",
            rule.id,
            rule.name,
            rule.next_run_at.isoformat() if rule.next_run_at else "n/a",
        )

    def reschedule(self, rule: RecurringTicketRule, now: datetime) -> None:
        rule.next_run_at = compute_next_run(
            rule.frequency, rule.day_of_week, rule.day_of_month, now=now
        )
