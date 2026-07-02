"""Add property-inspection tables (Phase 1.5)

Reusable inspection templates/checklists and the inspection instances performed
against an office, with per-item pass/fail/na results.

Revision ID: 067
Revises: 066
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = "067"
down_revision = "066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inspection_templates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_inspection_templates_organization_id",
        "inspection_templates",
        ["organization_id"],
    )

    op.create_table(
        "inspection_template_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("template_id", sa.UUID(), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["template_id"], ["inspection_templates.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_inspection_template_items_template_id",
        "inspection_template_items",
        ["template_id"],
    )

    op.create_table(
        "inspections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("template_id", sa.UUID(), nullable=True),
        sa.Column("office_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("status", sa.String(15), nullable=False, server_default="scheduled"),
        sa.Column("scheduled_date", sa.Date(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("inspector_id", sa.UUID(), nullable=True),
        sa.Column("overall_result", sa.String(4), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["template_id"], ["inspection_templates.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["office_id"], ["offices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["inspector_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inspections_organization_id", "inspections", ["organization_id"])
    op.create_index("ix_inspections_office_id", "inspections", ["office_id"])

    op.create_table(
        "inspection_item_results",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("inspection_id", sa.UUID(), nullable=False),
        sa.Column("template_item_id", sa.UUID(), nullable=True),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("result", sa.String(4), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["inspection_id"], ["inspections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["template_item_id"],
            ["inspection_template_items.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_inspection_item_results_inspection_id",
        "inspection_item_results",
        ["inspection_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inspection_item_results_inspection_id", table_name="inspection_item_results"
    )
    op.drop_table("inspection_item_results")
    op.drop_index("ix_inspections_office_id", table_name="inspections")
    op.drop_index("ix_inspections_organization_id", table_name="inspections")
    op.drop_table("inspections")
    op.drop_index(
        "ix_inspection_template_items_template_id",
        table_name="inspection_template_items",
    )
    op.drop_table("inspection_template_items")
    op.drop_index(
        "ix_inspection_templates_organization_id", table_name="inspection_templates"
    )
    op.drop_table("inspection_templates")
