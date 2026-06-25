"""add site_settings table

Revision ID: 009
Revises: 008
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "site_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("app_name", sa.String(200), nullable=False, server_default="SwiftLease"),
        sa.Column("login_subtitle", sa.Text(), nullable=True),
        sa.Column("login_form_header", sa.String(200), nullable=True),
        sa.Column("login_form_description", sa.Text(), nullable=True),
    )
    # Insert default row
    op.execute(
        "INSERT INTO site_settings (id, app_name) VALUES (1, 'SwiftLease')"
    )


def downgrade() -> None:
    op.drop_table("site_settings")
