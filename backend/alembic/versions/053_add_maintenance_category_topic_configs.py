"""Add org-scoped maintenance category topic configs.

Revision ID: 053
Revises: 052
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "maintenance_category_topic_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("subtopics", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "category",
            name="uq_maint_category_topic_config_org_category",
        ),
    )
    op.create_index(
        "idx_maint_topic_config_org",
        "maintenance_category_topic_configs",
        ["organization_id"],
    )
    op.create_index(
        "idx_maint_topic_config_category",
        "maintenance_category_topic_configs",
        ["category"],
    )


def downgrade() -> None:
    op.drop_index("idx_maint_topic_config_category", table_name="maintenance_category_topic_configs")
    op.drop_index("idx_maint_topic_config_org", table_name="maintenance_category_topic_configs")
    op.drop_table("maintenance_category_topic_configs")
