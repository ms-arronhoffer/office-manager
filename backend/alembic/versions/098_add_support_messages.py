"""Add support_messages (two-way support conversation thread)

Adds ``support_messages`` — reply messages forming the two-way conversation
thread on a support request. Messages are authored either by the requester (or
an org admin) in-app, or by platform support staff from the admin console
(``is_from_admin``).

Idempotent: guards on table existence so create_all+stamp fresh DBs and
already-migrated DBs both apply cleanly.

Revision ID: 098
Revises: 097
Create Date: 2026-07-10
"""
from alembic import op
import sqlalchemy as sa

revision = "098"
down_revision = "097"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "support_messages" in inspector.get_table_names():
        return
    op.create_table(
        "support_messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("support_request_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_from_admin", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("author_user_id", sa.UUID(), nullable=True),
        sa.Column("author_name", sa.String(255), nullable=True),
        sa.Column("author_email", sa.String(320), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["support_request_id"], ["support_requests.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_support_messages_support_request_id",
        "support_messages",
        ["support_request_id"],
    )
    op.create_index(
        "ix_support_messages_organization_id",
        "support_messages",
        ["organization_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "support_messages" in inspector.get_table_names():
        op.drop_table("support_messages")
