"""add user preferences column

Revision ID: 002_user_preferences
Revises: 001_add_indexes
Create Date: 2026-04-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("preferences", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("users", "preferences")
