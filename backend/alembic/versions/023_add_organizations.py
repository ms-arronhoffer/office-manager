"""Add organizations table and organization_id to all entity tables

Revision ID: 023
Revises: 022
Create Date: 2026-04-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None

DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_ORG_NAME = "Default Organization"
DEFAULT_ORG_SLUG = "default"

# Tables that get organization_id (top-level entities; child tables are scoped through parent FK)
ENTITY_TABLES = [
    "managers",
    "offices",
    "leases",
    "landlords",
    "vendors",
    "hvac_contracts",
    "office_transitions",
    "ticket_categories",
    "maintenance_tickets",
    "activity_log",
    "notifications",
    "email_reminder_rules",
    "ticket_templates",
    "recurring_ticket_rules",
    "attachments",
    "wizard_configs",
]


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # ── 1. Create organizations table ───────────────────────────────────────
    if not inspector.has_table("organizations"):
        op.create_table(
            "organizations",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("slug", sa.String(100), nullable=False, unique=True),
            sa.Column("plan", sa.String(20), nullable=False, server_default="starter"),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
            sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("stripe_customer_id", sa.String(255), nullable=True),
            sa.Column("stripe_subscription_id", sa.String(255), nullable=True),
            sa.Column("max_seats", sa.Integer, nullable=True),
            sa.Column("onboarding_complete", sa.Boolean, nullable=False, server_default="false"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )
        op.create_index("idx_organizations_slug", "organizations", ["slug"])

    # ── 2. Seed the default organization ────────────────────────────────────
    conn.execute(
        sa.text(
            "INSERT INTO organizations (id, name, slug, plan, is_active, onboarding_complete) "
            "VALUES (:id, :name, :slug, 'starter', true, true) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": DEFAULT_ORG_ID, "name": DEFAULT_ORG_NAME, "slug": DEFAULT_ORG_SLUG},
    )

    # ── 3. Add organization_id + is_super_admin to users ────────────────────
    existing_user_cols = [c["name"] for c in inspector.get_columns("users")]
    if "organization_id" not in existing_user_cols:
        op.add_column("users", sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.create_foreign_key(
            "fk_users_organization_id", "users", "organizations",
            ["organization_id"], ["id"],
        )
        op.create_index("idx_users_organization_id", "users", ["organization_id"])
    if "is_super_admin" not in existing_user_cols:
        op.add_column(
            "users",
            sa.Column("is_super_admin", sa.Boolean, nullable=False, server_default="false"),
        )

    # ── 4. Add organization_id to all entity tables ──────────────────────────
    for table in ENTITY_TABLES:
        if not inspector.has_table(table):
            continue
        existing_cols = [c["name"] for c in inspector.get_columns(table)]
        if "organization_id" in existing_cols:
            continue
        op.add_column(table, sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_organization_id", table, "organizations",
            ["organization_id"], ["id"],
        )
        op.create_index(f"idx_{table}_organization_id", table, ["organization_id"])

    # ── 5. Backfill all existing rows to the default org ────────────────────
    all_tables = ["users"] + ENTITY_TABLES
    for table in all_tables:
        if inspector.has_table(table):
            conn.execute(
                sa.text(f"UPDATE {table} SET organization_id = :org_id WHERE organization_id IS NULL"),
                {"org_id": DEFAULT_ORG_ID},
            )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    all_tables = ["users"] + list(reversed(ENTITY_TABLES))
    for table in all_tables:
        if not inspector.has_table(table):
            continue
        existing_cols = [c["name"] for c in inspector.get_columns(table)]
        if "organization_id" not in existing_cols:
            continue
        try:
            if table == "users":
                op.drop_constraint("fk_users_organization_id", "users", type_="foreignkey")
                op.drop_index("idx_users_organization_id", "users")
            else:
                op.drop_constraint(f"fk_{table}_organization_id", table, type_="foreignkey")
                op.drop_index(f"idx_{table}_organization_id", table)
        except Exception:
            pass
        op.drop_column(table, "organization_id")

    existing_user_cols = [c["name"] for c in inspector.get_columns("users")]
    if "is_super_admin" in existing_user_cols:
        op.drop_column("users", "is_super_admin")

    if inspector.has_table("organizations"):
        op.drop_table("organizations")
