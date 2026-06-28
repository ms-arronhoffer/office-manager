"""Single dispatcher for schedule-driven rule evaluators.

Holds a registry of :class:`~app.tasks.rule_evaluator.RuleEvaluator` instances
keyed by ``action_type`` and runs the due rules for one (or all) of them inside
a single database session, preserving the error-isolation and commit semantics
of the original recurring-ticket task:

* per-rule ``try/except`` so one failing rule never aborts the batch,
* a single commit at the end with rollback on failure.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.database import async_session
from app.tasks.rule_evaluator import RecurringTicketEvaluator, RuleEvaluator

logger = logging.getLogger(__name__)

# Registry of evaluators keyed by action type. Future rule types (e.g. COI
# expiration, scheduled reports) register here and gain the shared runner.
_REGISTRY: dict[str, RuleEvaluator] = {}


def register_evaluator(evaluator: RuleEvaluator) -> None:
    """Register an evaluator under its ``action_type`` (idempotent)."""
    if not evaluator.action_type:
        raise ValueError("Evaluator must define a non-empty action_type")
    _REGISTRY[evaluator.action_type] = evaluator


def get_evaluator(action_type: str) -> RuleEvaluator | None:
    return _REGISTRY.get(action_type)


# Built-in evaluators.
register_evaluator(RecurringTicketEvaluator())


async def run_due_rules(action_type: str) -> int:
    """Run all due rules for a single ``action_type``. Returns rules fired.

    Mirrors the original recurring-ticket loop: select due rules, fire each in
    isolation, and commit once at the end.
    """
    evaluator = get_evaluator(action_type)
    if evaluator is None:
        logger.warning("No evaluator registered for action type %r", action_type)
        return 0

    now = datetime.now(timezone.utc)
    logger.info("Running rule evaluator %r at %s", action_type, now.isoformat())

    fired = 0
    async with async_session() as db:
        try:
            rules = await evaluator.due_query(db, now)
        except Exception:
            logger.exception("Failed to query due rules for %r", action_type)
            return 0

        if not rules:
            logger.info("No %r rules due — skipping", action_type)
            return 0

        for rule in rules:
            try:
                await evaluator.fire(db, rule, now)
                fired += 1
            except Exception:
                logger.exception(
                    "Failed to process %r rule %s", action_type, getattr(rule, "id", "?")
                )

        try:
            await db.commit()
        except Exception:
            logger.exception("Failed to commit %r rules", action_type)
            await db.rollback()
            return 0

    return fired
