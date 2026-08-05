"""Add pgvector columns + HNSW indexes for embedding search.

Revision ID: 112
Revises: 111
Create Date: 2026-08-01

Adds a ``vector`` typed column alongside the existing JSONB ``embedding`` column
on both embedding tables and backfills it, so semantic ranking can be pushed
into Postgres (``ORDER BY embedding_vec <=> :query LIMIT n``) instead of loading
every row into application memory.

The JSONB column is deliberately retained: it remains the write path, the
backfill source, and the fallback used whenever the extension is unavailable.

Idempotent and degrade-safe: every pgvector-dependent step runs inside its own
SAVEPOINT, so a managed Postgres that cannot install the extension logs and
skips rather than aborting the migration chain. Also guards on table/column
existence so create_all+stamp fresh DBs and re-runs are no-ops.
"""
import logging

from alembic import op
import sqlalchemy as sa

revision = "112"
down_revision = "111"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

# ai_service.embed_texts requests 768 dimensions from every provider, which is
# the storage and HNSW index contract for both embedding tables.
_VECTOR_DIM = 768

_VECTOR_COLUMN = "embedding_vec"
# (table, hnsw index name)
_TARGETS = (
    ("knowledge_chunks", "idx_knowledge_chunks_embedding_hnsw"),
    ("lease_document_chunks", "idx_lease_doc_chunks_embedding_hnsw"),
)


def _run_optional(bind, statement: str, description: str) -> bool:
    """Execute ``statement`` in a SAVEPOINT; log and skip if it fails."""
    try:
        with bind.begin_nested():
            bind.execute(sa.text(statement))
        return True
    except Exception as exc:  # noqa: BLE001 - any pgvector gap must not brick the chain
        logger.warning("Migration 112: %s skipped (%s)", description, exc)
        return False


def _existing_tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _columns(bind, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()

    if not _run_optional(
        bind, "CREATE EXTENSION IF NOT EXISTS vector", "vector extension creation"
    ):
        logger.warning(
            "Migration 112: pgvector unavailable; embedding search stays on the "
            "JSONB + in-Python cosine fallback."
        )
        return

    tables = _existing_tables(bind)
    for table, index_name in _TARGETS:
        if table not in tables:
            continue

        if _VECTOR_COLUMN not in _columns(bind, table):
            if not _run_optional(
                bind,
                f"ALTER TABLE {table} "
                f"ADD COLUMN {_VECTOR_COLUMN} vector({_VECTOR_DIM})",
                f"{table}.{_VECTOR_COLUMN} column creation",
            ):
                continue

        # JSONB arrays render as '[0.1, 0.2, ...]', which is valid vector input.
        # Rows of another width are left null and keep using the Python path.
        _run_optional(
            bind,
            f"UPDATE {table} SET {_VECTOR_COLUMN} = embedding::text::vector "
            f"WHERE embedding IS NOT NULL "
            f"AND {_VECTOR_COLUMN} IS NULL "
            f"AND jsonb_typeof(embedding) = 'array' "
            f"AND jsonb_array_length(embedding) = {_VECTOR_DIM}",
            f"{table}.{_VECTOR_COLUMN} backfill",
        )

        # HNSW needs pgvector >= 0.5.0; older builds only ship ivfflat.
        _run_optional(
            bind,
            f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} "
            f"USING hnsw ({_VECTOR_COLUMN} vector_cosine_ops)",
            f"{index_name} HNSW index creation",
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = _existing_tables(bind)
    for table, index_name in _TARGETS:
        if table not in tables:
            continue
        _run_optional(bind, f"DROP INDEX IF EXISTS {index_name}", f"{index_name} drop")
        if _VECTOR_COLUMN in _columns(bind, table):
            _run_optional(
                bind,
                f"ALTER TABLE {table} DROP COLUMN {_VECTOR_COLUMN}",
                f"{table}.{_VECTOR_COLUMN} drop",
            )
    # The extension is intentionally left installed; other objects may depend on it.
