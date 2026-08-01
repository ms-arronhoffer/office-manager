"""Add per-organization OIDC SSO configuration + login state

Adds the tables backing single sign-on (Administration -> People & Access ->
Single Sign-On):

  - ``organization_sso_configs`` — one IdP connection per org, client secret
    encrypted at rest (see app.utils.crypto)
  - ``sso_login_states``        — single-use, expiring authorization-request
    state carrying the PKCE verifier and nonce

Revision ID: 113
Revises: 112
Create Date: 2026-08-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "113"
down_revision = "112"
branch_labels = None
depends_on = None


def _existing_tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _existing_tables()

    if "organization_sso_configs" not in tables:
        op.create_table(
            "organization_sso_configs",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("organization_id", sa.UUID(), nullable=False),
            sa.Column("provider", sa.String(20), nullable=False, server_default="oidc"),
            sa.Column("issuer", sa.String(500), nullable=False),
            sa.Column("client_id", sa.String(255), nullable=False),
            sa.Column("client_secret_encrypted", sa.Text(), nullable=False),
            sa.Column(
                "allowed_email_domains",
                postgresql.JSONB(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column("enforce_sso", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("default_role", sa.String(20), nullable=False, server_default="viewer"),
            sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("organization_id", name="uq_org_sso_config_org"),
        )
        op.create_index(
            "ix_organization_sso_configs_organization_id",
            "organization_sso_configs",
            ["organization_id"],
        )

    if "sso_login_states" not in tables:
        op.create_table(
            "sso_login_states",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("state", sa.String(128), nullable=False),
            sa.Column("organization_id", sa.UUID(), nullable=False),
            sa.Column("code_verifier", sa.String(128), nullable=False),
            sa.Column("nonce", sa.String(128), nullable=False),
            sa.Column("redirect_uri", sa.String(500), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("state", name="uq_sso_login_state_state"),
        )
        op.create_index("ix_sso_login_states_state", "sso_login_states", ["state"])
        op.create_index(
            "ix_sso_login_states_organization_id", "sso_login_states", ["organization_id"]
        )
        op.create_index("ix_sso_login_states_expires_at", "sso_login_states", ["expires_at"])


def downgrade() -> None:
    tables = _existing_tables()
    if "sso_login_states" in tables:
        op.drop_index("ix_sso_login_states_expires_at", table_name="sso_login_states")
        op.drop_index("ix_sso_login_states_organization_id", table_name="sso_login_states")
        op.drop_index("ix_sso_login_states_state", table_name="sso_login_states")
        op.drop_table("sso_login_states")
    if "organization_sso_configs" in tables:
        op.drop_index(
            "ix_organization_sso_configs_organization_id",
            table_name="organization_sso_configs",
        )
        op.drop_table("organization_sso_configs")
