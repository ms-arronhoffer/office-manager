"""Scheduled rebuild of the portfolio knowledge index (AI assistant, Phase 3).

Walks every organization and rebuilds its :class:`~app.models.knowledge_chunk.
KnowledgeChunk` index (maintenance tickets, leases, lease abstracts) so the
``/ai/assistant/query`` retrieval stays current as records change. Indexing is
idempotent (each org's chunks are replaced wholesale).

Degrades gracefully: when Gemini is not configured chunks are still rebuilt
keyword-only, so the assistant's keyword fallback keeps working. Per-org failures
are logged and skipped rather than aborting the whole run.
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.organization import Organization
from app.services import knowledge_service

logger = logging.getLogger(__name__)


async def reindex_knowledge() -> None:
    """Entry point invoked by the scheduler."""
    async for db in get_db():
        await _run(db)
        break


async def _run(db: AsyncSession) -> None:
    try:
        org_ids = (await db.execute(select(Organization.id))).scalars().all()
    except Exception:
        logger.exception("Failed to load organizations for knowledge reindex")
        return

    total = 0
    for org_id in org_ids:
        try:
            total += await knowledge_service.reindex_organization(db, org_id)
        except Exception:
            logger.exception("Knowledge reindex failed for org %s", org_id)
            try:
                await db.rollback()
            except Exception:
                logger.exception("Rollback failed after knowledge reindex error")

    logger.info("Knowledge index rebuilt: %s chunks across %s orgs", total, len(org_ids))
