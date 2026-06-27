"""Add maintenance program tables (assets, tasks, logs).

Introduces the broader **Maintenance** domain that supersedes the narrow HVAC
surface: physical assets, recurring maintenance tasks (with vendor assignment and
reminder settings), and service logs. All three tables are org-scoped.

Revision ID: 052
Revises: 051
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "052"
down_revision = "051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "maintenance_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("subtopic", sa.String(length=60), nullable=True),
        sa.Column("office_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("location_desc", sa.String(length=255), nullable=True),
        sa.Column("make", sa.String(length=100), nullable=True),
        sa.Column("model", sa.String(length=150), nullable=True),
        sa.Column("serial_number", sa.String(length=100), nullable=True),
        sa.Column("install_date", sa.Date(), nullable=True),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_regulatory", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("certification_expiry", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=30), server_default="active", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["office_id"], ["offices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["vendor_id"], ["vendors.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_maint_asset_org", "maintenance_assets", ["organization_id"])
    op.create_index("idx_maint_asset_category", "maintenance_assets", ["category"])
    op.create_index("idx_maint_asset_office", "maintenance_assets", ["office_id"])
    op.create_index("idx_maint_asset_vendor", "maintenance_assets", ["vendor_id"])

    op.create_table(
        "maintenance_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("subtopic", sa.String(length=60), nullable=True),
        sa.Column("office_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("frequency", sa.String(length=30), nullable=True),
        sa.Column("last_completed_date", sa.Date(), nullable=True),
        sa.Column("next_due_date", sa.Date(), nullable=True),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=30), server_default="scheduled", nullable=False),
        sa.Column("is_regulatory", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("reminder_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("reminder_days_before", sa.Integer(), server_default="14", nullable=False),
        sa.Column(
            "reminder_recipients",
            postgresql.ARRAY(sa.String(length=255)),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["asset_id"], ["maintenance_assets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["office_id"], ["offices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["vendor_id"], ["vendors.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_maint_task_org", "maintenance_tasks", ["organization_id"])
    op.create_index("idx_maint_task_category", "maintenance_tasks", ["category"])
    op.create_index("idx_maint_task_office", "maintenance_tasks", ["office_id"])
    op.create_index("idx_maint_task_vendor", "maintenance_tasks", ["vendor_id"])
    op.create_index("idx_maint_task_due", "maintenance_tasks", ["next_due_date"])

    op.create_table(
        "maintenance_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("service_date", sa.Date(), nullable=True),
        sa.Column("performed_by", sa.String(length=255), nullable=True),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cost", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("invoice_number", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["maintenance_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["maintenance_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vendor_id"], ["vendors.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_maint_log_org", "maintenance_logs", ["organization_id"])
    op.create_index("idx_maint_log_task", "maintenance_logs", ["task_id"])
    op.create_index("idx_maint_log_asset", "maintenance_logs", ["asset_id"])


def downgrade() -> None:
    op.drop_table("maintenance_logs")
    op.drop_table("maintenance_tasks")
    op.drop_table("maintenance_assets")
