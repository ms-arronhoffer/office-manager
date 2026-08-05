"""Add resident payment methods and lease autopay.

Revision ID: 111
Revises: 110
Create Date: 2026-08-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "111"
down_revision = "110"
branch_labels = None
depends_on = None

_METHODS = "resident_payment_methods"
_LEASES = "resident_leases"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _METHODS not in inspector.get_table_names():
        op.create_table(
            _METHODS,
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "organization_id",
                UUID(as_uuid=True),
                sa.ForeignKey("organizations.id"),
                nullable=True,
            ),
            sa.Column(
                "resident_id",
                UUID(as_uuid=True),
                sa.ForeignKey("residents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "processor",
                sa.String(30),
                nullable=False,
                server_default="stripe",
            ),
            # Opaque processor handle only. Full card/bank numbers are never stored.
            sa.Column("processor_token", sa.String(255), nullable=False),
            sa.Column("brand", sa.String(40), nullable=True),
            sa.Column("last4", sa.String(4), nullable=True),
            sa.Column("exp_month", sa.Integer(), nullable=True),
            sa.Column("exp_year", sa.Integer(), nullable=True),
            sa.Column(
                "is_default", sa.Boolean(), nullable=False, server_default="false"
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )
        op.create_index(
            "idx_resident_payment_methods_org", _METHODS, ["organization_id"]
        )
        op.create_index(
            "idx_resident_payment_methods_resident", _METHODS, ["resident_id"]
        )

    lease_columns = {c["name"] for c in inspector.get_columns(_LEASES)}
    if "autopay_enabled" not in lease_columns:
        op.add_column(
            _LEASES,
            sa.Column(
                "autopay_enabled",
                sa.Boolean(),
                nullable=False,
                server_default="false",
            ),
        )
    if "autopay_payment_method_id" not in lease_columns:
        op.add_column(
            _LEASES,
            sa.Column("autopay_payment_method_id", UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            "fk_resident_leases_autopay_method",
            _LEASES,
            _METHODS,
            ["autopay_payment_method_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    lease_columns = {c["name"] for c in inspector.get_columns(_LEASES)}
    if "autopay_payment_method_id" in lease_columns:
        op.drop_constraint(
            "fk_resident_leases_autopay_method", _LEASES, type_="foreignkey"
        )
        op.drop_column(_LEASES, "autopay_payment_method_id")
    if "autopay_enabled" in lease_columns:
        op.drop_column(_LEASES, "autopay_enabled")

    if _METHODS in inspector.get_table_names():
        op.drop_index("idx_resident_payment_methods_resident", table_name=_METHODS)
        op.drop_index("idx_resident_payment_methods_org", table_name=_METHODS)
        op.drop_table(_METHODS)
