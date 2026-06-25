"""recreate ticket_notes if missing (dropped by startup script that has been removed)

Revision ID: 022
Revises: 021
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if not inspector.has_table("ticket_notes"):
        op.create_table(
            "ticket_notes",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("ticket_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("maintenance_tickets.id", ondelete="CASCADE"), nullable=False),
            sa.Column("note_text", sa.Text, nullable=False),
            sa.Column("note_order", sa.Integer, nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("created_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        )


def downgrade() -> None:
    pass
