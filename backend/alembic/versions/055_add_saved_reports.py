"""Saved & scheduled reports.

Revision ID: 055
Revises: 054
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "055"
down_revision = "054b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("dataset", sa.String(length=50), nullable=False),
        sa.Column("columns", postgresql.ARRAY(sa.String(length=100)), nullable=True),
        sa.Column("filters", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("format", sa.String(length=10), nullable=False, server_default="pdf"),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_saved_reports_organization_id", "saved_reports", ["organization_id"]
    )

    op.create_table(
        "report_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("saved_report_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("frequency", sa.String(length=20), nullable=False),
        sa.Column("day_of_week", sa.Integer(), nullable=True),
        sa.Column("day_of_month", sa.Integer(), nullable=True),
        sa.Column("recipients", postgresql.ARRAY(sa.String(length=255)), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["saved_report_id"], ["saved_reports.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_report_schedules_organization_id", "report_schedules", ["organization_id"]
    )
    op.create_index(
        "ix_report_schedules_saved_report_id", "report_schedules", ["saved_report_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_report_schedules_saved_report_id", table_name="report_schedules")
    op.drop_index("ix_report_schedules_organization_id", table_name="report_schedules")
    op.drop_table("report_schedules")
    op.drop_index("ix_saved_reports_organization_id", table_name="saved_reports")
    op.drop_table("saved_reports")
