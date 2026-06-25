"""add ASC 842 / IFRS 16 accounting fields to leases

Revision ID: 013
Revises: 012
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None

_COLS = [
    ("lease_commencement_date", sa.Date(), None),
    ("accounting_standard", sa.String(10), None),
    ("lease_classification", sa.String(20), None),
    ("payment_amount", sa.Numeric(15, 2), None),
    ("payment_frequency", sa.String(20), None),
    ("annual_escalation_rate", sa.Numeric(8, 6), None),
    ("incremental_borrowing_rate", sa.Numeric(8, 6), None),
    ("initial_direct_costs", sa.Numeric(15, 2), None),
    ("lease_incentives", sa.Numeric(15, 2), None),
    ("prepaid_rent", sa.Numeric(15, 2), None),
    ("residual_value_guarantee", sa.Numeric(15, 2), None),
    ("is_short_term_lease", sa.Boolean(), False),
    ("is_low_value_lease", sa.Boolean(), False),
    ("currency", sa.String(3), "USD"),
]


def upgrade() -> None:
    for col_name, col_type, server_default in _COLS:
        kwargs: dict = {"nullable": True}
        if server_default is not None:
            if isinstance(server_default, str):
                kwargs["server_default"] = server_default
            else:
                kwargs["server_default"] = str(server_default)
        op.add_column("leases", sa.Column(col_name, col_type, **kwargs))


def downgrade() -> None:
    for col_name, _, __ in reversed(_COLS):
        op.drop_column("leases", col_name)
