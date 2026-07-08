"""Link resident leases to their lease template and custom field values

Adds two columns to ``resident_leases`` so a lease remembers the template it was
prepared from (driving e-signing without re-selecting a template) and stores the
values for any custom ``{{merge_field}}`` placeholders the template defines beyond
the standard lease/unit/occupant fields.

Revision ID: 076
Revises: 075
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "076"
down_revision = "075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "resident_leases",
        sa.Column("lease_template_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "resident_leases",
        sa.Column("template_field_values", postgresql.JSONB(), nullable=True),
    )
    op.create_foreign_key(
        "fk_resident_leases_lease_template",
        "resident_leases",
        "lease_templates",
        ["lease_template_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_resident_leases_lease_template", "resident_leases", type_="foreignkey"
    )
    op.drop_column("resident_leases", "template_field_values")
    op.drop_column("resident_leases", "lease_template_id")
