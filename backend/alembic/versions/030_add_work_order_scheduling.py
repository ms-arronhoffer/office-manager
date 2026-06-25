"""add work order scheduling and cost lines

Revision ID: 030
Revises: 029
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Scheduling fields on maintenance_tickets
    op.add_column("maintenance_tickets", sa.Column("scheduled_date", sa.DateTime(timezone=True), nullable=True))
    op.add_column("maintenance_tickets", sa.Column("estimated_duration_minutes", sa.Integer(), nullable=True))
    op.add_column("maintenance_tickets", sa.Column("actual_start_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("maintenance_tickets", sa.Column("actual_end_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("maintenance_tickets", sa.Column("technician_name", sa.String(255), nullable=True))

    # Work order cost lines table
    op.create_table(
        "work_order_cost_lines",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("ticket_id", sa.UUID(), sa.ForeignKey("maintenance_tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("line_type", sa.String(20), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("quantity", sa.Numeric(10, 2), nullable=False, server_default="1"),
        sa.Column("unit_cost", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_work_order_cost_lines_ticket", "work_order_cost_lines", ["ticket_id"])


def downgrade() -> None:
    op.drop_index("idx_work_order_cost_lines_ticket", table_name="work_order_cost_lines")
    op.drop_table("work_order_cost_lines")

    op.drop_column("maintenance_tickets", "technician_name")
    op.drop_column("maintenance_tickets", "actual_end_at")
    op.drop_column("maintenance_tickets", "actual_start_at")
    op.drop_column("maintenance_tickets", "estimated_duration_minutes")
    op.drop_column("maintenance_tickets", "scheduled_date")
