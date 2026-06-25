"""add ticket_templates table

Revision ID: 010
Revises: 009
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ticket_templates",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(20), nullable=False, server_default="low"),
        sa.Column("category_id", sa.UUID(), sa.ForeignKey("ticket_categories.id"), nullable=True),
        sa.Column("office_id", sa.UUID(), sa.ForeignKey("offices.id"), nullable=True),
        sa.Column("assigned_to_id", sa.UUID(), sa.ForeignKey("managers.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("ticket_templates")
