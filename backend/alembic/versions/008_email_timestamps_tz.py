"""convert email_log.sent_at and email_reminder_rules.last_triggered_at to TIMESTAMP WITH TIME ZONE

Revision ID: 008
Revises: 007
Create Date: 2026-04-26

The Python code stores timezone-aware UTC datetimes (datetime.now(timezone.utc)),
but the original migration declared these columns as plain TIMESTAMP, which
asyncpg refuses to mix with aware datetimes:

    asyncpg.exceptions.DataError: invalid input for query argument $6:
    can't subtract offset-naive and offset-aware datetimes

This migration converts both columns in-place. Postgres can ALTER from
TIMESTAMP to TIMESTAMPTZ without rewriting the table; existing values are
treated as being in the server's local timezone (which is UTC inside the
official postgres:* images). The conversion is therefore safe.
"""

from alembic import op
import sqlalchemy as sa


revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def _column_type(table: str, column: str) -> str:
    """Return the lowercase data_type string Postgres reports for a column."""
    bind = op.get_bind()
    res = bind.execute(
        sa.text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    )
    row = res.first()
    return (row[0] if row else "").lower()


def _ensure_tz(table: str, column: str) -> None:
    """Convert column to TIMESTAMPTZ if it isn't already."""
    current = _column_type(table, column)
    if "with time zone" in current:
        return
    # USING clause is required to tell Postgres how to interpret existing data.
    # Treat naive values as UTC (matches the application's convention).
    op.execute(
        sa.text(
            f"ALTER TABLE {table} "
            f"ALTER COLUMN {column} TYPE TIMESTAMP WITH TIME ZONE "
            f"USING {column} AT TIME ZONE 'UTC'"
        )
    )


def upgrade() -> None:
    _ensure_tz("email_log", "sent_at")
    _ensure_tz("email_reminder_rules", "last_triggered_at")


def downgrade() -> None:
    # Convert back to naive timestamps. Strip the timezone offset by casting
    # via the UTC timezone first, then dropping the tz info.
    op.execute(
        sa.text(
            "ALTER TABLE email_log "
            "ALTER COLUMN sent_at TYPE TIMESTAMP WITHOUT TIME ZONE "
            "USING sent_at AT TIME ZONE 'UTC'"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE email_reminder_rules "
            "ALTER COLUMN last_triggered_at TYPE TIMESTAMP WITHOUT TIME ZONE "
            "USING last_triggered_at AT TIME ZONE 'UTC'"
        )
    )
