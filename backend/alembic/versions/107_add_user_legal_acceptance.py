"""Add legal acceptance columns to users

Captures each user's acceptance of the required legal documents (Terms of
Service, EULA, Privacy Policy, Acceptable Use Policy) for auditing:
``legal_accepted_at`` records when the user accepted and
``legal_accepted_versions`` snapshots the ``slug -> version`` map that was
accepted, so we can prove which version of each document a given user agreed to.

The org creator's acceptance is recorded at signup; every other user must accept
on first login before their account is treated as active.

Idempotent: guards on column existence so create_all+stamp fresh DBs and
already-migrated DBs both apply cleanly.

Revision ID: 107
Revises: 106
Create Date: 2026-07-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "107"
down_revision = "106"
branch_labels = None
depends_on = None

_TABLE = "users"


def _columns(inspector) -> set[str]:
    return {c["name"] for c in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return
    cols = _columns(inspector)
    if "legal_accepted_at" not in cols:
        op.add_column(
            _TABLE, sa.Column("legal_accepted_at", sa.DateTime(timezone=True), nullable=True)
        )
    if "legal_accepted_versions" not in cols:
        op.add_column(
            _TABLE,
            sa.Column(
                "legal_accepted_versions",
                JSONB(),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return
    cols = _columns(inspector)
    if "legal_accepted_versions" in cols:
        op.drop_column(_TABLE, "legal_accepted_versions")
    if "legal_accepted_at" in cols:
        op.drop_column(_TABLE, "legal_accepted_at")
