"""Promote all admin users to super-admin status

Revision ID: 036
Revises: 035
Create Date: 2026-04-29
"""
from alembic import op
import sqlalchemy as sa


revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Set is_super_admin=True for all users with role='admin'
    op.execute(
        sa.text("UPDATE users SET is_super_admin = TRUE WHERE role = 'admin'")
    )


def downgrade() -> None:
    # Set is_super_admin=False for all users with role='admin'
    op.execute(
        sa.text("UPDATE users SET is_super_admin = FALSE WHERE role = 'admin'")
    )
