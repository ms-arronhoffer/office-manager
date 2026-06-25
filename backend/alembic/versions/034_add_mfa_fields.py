"""Add TOTP MFA fields to users

Revision ID: 034
Revises: 033
Create Date: 2026-04-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("totp_secret", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("users", sa.Column("totp_backup_codes", postgresql.JSONB(), nullable=True))
    op.add_column("users", sa.Column("mfa_challenge_token", sa.String(64), nullable=True))
    op.add_column(
        "users",
        sa.Column("mfa_challenge_expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "mfa_challenge_expires_at")
    op.drop_column("users", "mfa_challenge_token")
    op.drop_column("users", "totp_backup_codes")
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
