"""Email rule engine: structured recipients, escalation, digest, acknowledgement.

Revision ID: 054
Revises: 053
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "054b"
down_revision = "054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Extend email_reminder_rules ──────────────────────────────────────────
    op.add_column(
        "email_reminder_rules",
        sa.Column("recipient_roles", postgresql.ARRAY(sa.String(length=20)), nullable=True),
    )
    op.add_column(
        "email_reminder_rules",
        sa.Column(
            "recipient_user_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=True,
        ),
    )
    op.add_column(
        "email_reminder_rules",
        sa.Column(
            "delivery_mode",
            sa.String(length=20),
            nullable=False,
            server_default="immediate",
        ),
    )
    op.add_column(
        "email_reminder_rules",
        sa.Column("escalation_offsets", postgresql.ARRAY(sa.Integer()), nullable=True),
    )
    op.add_column(
        "email_reminder_rules",
        sa.Column(
            "escalation_recipient_emails",
            postgresql.ARRAY(sa.String(length=255)),
            nullable=True,
        ),
    )
    op.add_column(
        "email_reminder_rules",
        sa.Column(
            "require_acknowledgement",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # ── Extend email_log ─────────────────────────────────────────────────────
    op.add_column(
        "email_log",
        sa.Column("escalation_level", sa.Integer(), nullable=False, server_default="0"),
    )

    # ── New email_acknowledgements ───────────────────────────────────────────
    op.create_table(
        "email_acknowledgements",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("ack_token", sa.String(length=64), nullable=False),
        sa.Column("escalation_level", sa.Integer(), nullable=False, server_default="-1"),
        sa.Column("first_sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["rule_id"], ["email_reminder_rules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ack_token", name="uq_email_ack_token"),
    )
    op.create_index("idx_email_ack_org", "email_acknowledgements", ["organization_id"])
    op.create_index("idx_email_ack_rule", "email_acknowledgements", ["rule_id"])
    op.create_index("ix_email_acknowledgements_ack_token", "email_acknowledgements", ["ack_token"])
    op.create_index(
        "idx_email_ack_rule_entity",
        "email_acknowledgements",
        ["rule_id", "entity_type", "entity_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_email_ack_rule_entity", table_name="email_acknowledgements")
    op.drop_index("ix_email_acknowledgements_ack_token", table_name="email_acknowledgements")
    op.drop_index("idx_email_ack_rule", table_name="email_acknowledgements")
    op.drop_index("idx_email_ack_org", table_name="email_acknowledgements")
    op.drop_table("email_acknowledgements")

    op.drop_column("email_log", "escalation_level")

    op.drop_column("email_reminder_rules", "require_acknowledgement")
    op.drop_column("email_reminder_rules", "escalation_recipient_emails")
    op.drop_column("email_reminder_rules", "escalation_offsets")
    op.drop_column("email_reminder_rules", "delivery_mode")
    op.drop_column("email_reminder_rules", "recipient_user_ids")
    op.drop_column("email_reminder_rules", "recipient_roles")
