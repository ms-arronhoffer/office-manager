"""add email_reminder_rules and email_log tables

Revision ID: 006
Revises: 005
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_reminder_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rule_name", sa.String(255), nullable=False),
        sa.Column("rule_type", sa.String(30), nullable=False),
        sa.Column("days_before", sa.Integer(), nullable=False),
        sa.Column("recipient_emails", ARRAY(sa.String(255)), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "email_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rule_id", sa.Uuid(), sa.ForeignKey("email_reminder_rules.id"), nullable=True),
        sa.Column("sent_to", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("status", sa.String(20), nullable=False, server_default="sent"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_email_log_rule_id", "email_log", ["rule_id"])
    op.create_index("idx_email_log_sent_at", "email_log", ["sent_at"])


def downgrade() -> None:
    op.drop_index("idx_email_log_sent_at", table_name="email_log")
    op.drop_index("idx_email_log_rule_id", table_name="email_log")
    op.drop_table("email_log")
    op.drop_table("email_reminder_rules")
