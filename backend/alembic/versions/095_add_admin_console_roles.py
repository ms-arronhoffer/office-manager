"""Add standalone admin console roles

Revision ID: 095
Revises: 081
Create Date: 2026-07-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "095"
down_revision = "081"
branch_labels = None
depends_on = None


ROLE_VALUES = ("super_admin", "support", "finance")


def upgrade() -> None:
    op.create_table(
        "admin_role_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("console_role", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", name="uq_admin_role_assignments_user_id"),
    )
    op.create_index(
        "ix_admin_role_assignments_user_id",
        "admin_role_assignments",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_admin_role_assignments_console_role",
        "admin_role_assignments",
        ["console_role"],
        unique=False,
    )
    op.create_check_constraint(
        "ck_admin_role_assignments_console_role",
        "admin_role_assignments",
        f"console_role IN {ROLE_VALUES}",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_admin_role_assignments_console_role",
        "admin_role_assignments",
        type_="check",
    )
    op.drop_index("ix_admin_role_assignments_console_role", table_name="admin_role_assignments")
    op.drop_index("ix_admin_role_assignments_user_id", table_name="admin_role_assignments")
    op.drop_table("admin_role_assignments")
