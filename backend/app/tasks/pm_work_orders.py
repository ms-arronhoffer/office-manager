"""APScheduler task: auto-generate preventive-maintenance work orders.

Scans every automation-enabled :class:`~app.models.maintenance.MaintenanceTask`
whose ``next_due_date`` has entered its lead window and spawns a work-order
ticket for each, de-duplicated per due cycle. Runs in a single session with a
single commit, mirroring the other scheduler tasks.
"""
import logging

from app.database import async_session
from app.services.pm_service import generate_due_work_orders

logger = logging.getLogger(__name__)


async def generate_pm_work_orders() -> None:
    async with async_session() as db:
        try:
            created = await generate_due_work_orders(db)
        except Exception:
            logger.exception("Preventive-maintenance work-order generation failed")
            await db.rollback()
            return

        if not created:
            logger.info("[PM WORK ORDERS] No due tasks — nothing generated")
            return

        try:
            await db.commit()
        except Exception:
            logger.exception("Failed to commit PM work orders")
            await db.rollback()
            return

        logger.info("[PM WORK ORDERS] Generated %d work order(s)", len(created))
