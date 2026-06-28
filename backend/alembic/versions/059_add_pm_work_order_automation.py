"""Preventive-maintenance work-order automation.

Adds the columns the PM automation engine needs:

* ``maintenance_tasks.auto_generate_work_order`` / ``work_order_lead_days`` /
  ``last_generated_due_date`` — opt-in flag, lead time, and the dedup marker that
  records the due cycle a work order was last generated for.
* ``maintenance_tickets.source_task_id`` — links an auto-generated work order
  back to its originating maintenance task (for compliance + dedup).

Revision ID: 059
Revises: 058
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "059"
down_revision = "058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "maintenance_tasks",
        sa.Column(
            "auto_generate_work_order",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "maintenance_tasks",
        sa.Column(
            "work_order_lead_days",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "maintenance_tasks",
        sa.Column("last_generated_due_date", sa.Date(), nullable=True),
    )

    op.add_column(
        "maintenance_tickets",
        sa.Column("source_task_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_maint_ticket_source_task",
        "maintenance_tickets",
        "maintenance_tasks",
        ["source_task_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_maint_ticket_source_task", "maintenance_tickets", ["source_task_id"]
    )

    # Ticket-category names are scoped per organization rather than globally
    # unique, so each tenant can own a "Preventive Maintenance" category.
    op.drop_constraint("ticket_categories_name_key", "ticket_categories", type_="unique")
    op.create_unique_constraint(
        "uq_ticket_category_org_name",
        "ticket_categories",
        ["organization_id", "name"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_ticket_category_org_name", "ticket_categories", type_="unique"
    )
    op.create_unique_constraint(
        "ticket_categories_name_key", "ticket_categories", ["name"]
    )

    op.drop_index("idx_maint_ticket_source_task", table_name="maintenance_tickets")
    op.drop_constraint(
        "fk_maint_ticket_source_task", "maintenance_tickets", type_="foreignkey"
    )
    op.drop_column("maintenance_tickets", "source_task_id")
    op.drop_column("maintenance_tasks", "last_generated_due_date")
    op.drop_column("maintenance_tasks", "work_order_lead_days")
    op.drop_column("maintenance_tasks", "auto_generate_work_order")
