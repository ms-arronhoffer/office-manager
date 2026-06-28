"""Nightly audit log pruning job.

Deletes ActivityLog rows older than each organization's configured retention
period (``audit_retention_days`` entitlement). Runs at 02:00 UTC each night.

Organizations whose plan grants unlimited retention (``None``) are skipped.
Processing is done in batches to avoid long-running transactions.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.activity_log import ActivityLog
from app.models.organization import Organization
from app.services import entitlements as ent

logger = logging.getLogger(__name__)

_BATCH_SIZE = 500


async def _prune_org(db: AsyncSession, org: Organization) -> int:
    """Delete stale ActivityLog rows for a single org. Returns count deleted."""
    retention_days = ent.get_limit(org, "audit_retention_days")
    if retention_days is None:
        return 0  # unlimited retention — skip

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    deleted = 0

    while True:
        # Fetch a batch of IDs to delete
        id_rows = await db.execute(
            select(ActivityLog.id)
            .where(
                ActivityLog.organization_id == org.id,
                ActivityLog.created_at < cutoff,
            )
            .limit(_BATCH_SIZE)
        )
        ids = [r[0] for r in id_rows.all()]
        if not ids:
            break

        await db.execute(delete(ActivityLog).where(ActivityLog.id.in_(ids)))
        await db.commit()
        deleted += len(ids)

        if len(ids) < _BATCH_SIZE:
            break

    return deleted


async def run_audit_log_pruning() -> None:
    """Main entry point called by the scheduler."""
    total_deleted = 0

    async with async_session() as db:
        result = await db.execute(select(Organization).where(Organization.is_active.is_(True)))
        orgs = result.scalars().all()
        org_count = len(orgs)

        for org in orgs:
            try:
                count = await _prune_org(db, org)
                if count:
                    logger.info("Pruned %s audit-log rows for org '%s'", count, org.name)
                total_deleted += count
            except Exception as e:
                logger.warning("Audit-log pruning failed for org '%s': %s", org.name, e)

        logger.info(
            "Audit-log pruning complete: %s rows deleted across %s orgs",
            total_deleted,
            org_count,
        )
