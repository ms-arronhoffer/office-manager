"""Index waiver recipients for duplicate-email lookups.

Adds a case-insensitive expression index on (organization_id,
lower(recipient_email)) so the "no duplicate pending waiver per (template,
email)" check and recipient search stay fast as request volume grows. No hard
unique constraint is added on purpose: re-sending after a waiver is
signed/declined/expired must remain possible, and the same person may receive
different waiver types.

Revision ID: 049
Revises: 048
"""
from alembic import op

revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_waiver_requests_org_email_lower "
        "ON waiver_requests (organization_id, lower(recipient_email))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_waiver_requests_org_email_lower")
