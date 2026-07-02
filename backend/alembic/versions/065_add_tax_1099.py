"""Add tax / 1099 tracking fields (Phase 1.3)

Adds vendor tax-classification fields and per-payment 1099 override columns so
finance staff can produce 1099-NEC / 1099-MISC totals from the existing AP
payment history.

Revision ID: 065
Revises: 064
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = "065"
down_revision = "064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vendors",
        sa.Column(
            "is_1099_vendor",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column("vendors", sa.Column("tax_id", sa.String(20), nullable=True))
    op.add_column("vendors", sa.Column("tax_id_type", sa.String(4), nullable=True))
    op.add_column("vendors", sa.Column("legal_name", sa.String(255), nullable=True))
    op.add_column(
        "vendors", sa.Column("tax_classification", sa.String(20), nullable=True)
    )
    op.add_column(
        "vendors", sa.Column("default_tax_box", sa.String(10), nullable=True)
    )

    op.add_column(
        "vendor_payments", sa.Column("is_reportable", sa.Boolean(), nullable=True)
    )
    op.add_column(
        "vendor_payments", sa.Column("tax_box", sa.String(10), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("vendor_payments", "tax_box")
    op.drop_column("vendor_payments", "is_reportable")
    op.drop_column("vendors", "default_tax_box")
    op.drop_column("vendors", "tax_classification")
    op.drop_column("vendors", "legal_name")
    op.drop_column("vendors", "tax_id_type")
    op.drop_column("vendors", "tax_id")
    op.drop_column("vendors", "is_1099_vendor")
