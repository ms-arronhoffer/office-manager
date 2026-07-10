"""Merge concurrent heads after email verification migration

Revision ID: 096
Revises: 082, 090, 095
Create Date: 2026-07-10
"""

revision = "096"
down_revision = ("082", "090", "095")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
