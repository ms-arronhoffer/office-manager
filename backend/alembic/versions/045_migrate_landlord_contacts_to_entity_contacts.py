"""Migrate landlord_contacts into the polymorphic entity_contacts table

Copies any existing rows from the legacy ``landlord_contacts`` table into the
reusable ``entity_contacts`` table (``entity_type = 'landlord'``) so landlords
share the same additional-contacts system as vendors and management companies.
The legacy table is left in place to avoid data loss; the UI now reads/writes
landlord contacts through ``/api/v1/contacts``.

Revision ID: 045
Revises: 044
Create Date: 2026-06-25
"""
from alembic import op

revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Copy legacy landlord contacts into entity_contacts. Pull organization_id
    # from the parent landlord and only insert rows that haven't already been
    # migrated (idempotent on re-run).
    op.execute(
        """
        INSERT INTO entity_contacts (
            id, organization_id, entity_type, entity_id,
            contact_name, title, contact_type, is_primary,
            email, phone, notes, created_at, updated_at
        )
        SELECT
            lc.id,
            l.organization_id,
            'landlord',
            lc.landlord_id,
            lc.contact_name,
            lc.title,
            lc.contact_type,
            lc.is_primary,
            lc.email,
            lc.phone,
            lc.notes,
            lc.created_at,
            lc.updated_at
        FROM landlord_contacts lc
        JOIN landlords l ON l.id = lc.landlord_id
        WHERE NOT EXISTS (
            SELECT 1 FROM entity_contacts ec WHERE ec.id = lc.id
        )
        """
    )


def downgrade() -> None:
    # Remove rows that were copied from landlord_contacts (those whose id still
    # exists in the legacy table). Landlord contacts created directly via the
    # new system after migration are intentionally preserved.
    op.execute(
        """
        DELETE FROM entity_contacts ec
        WHERE ec.entity_type = 'landlord'
          AND EXISTS (
            SELECT 1 FROM landlord_contacts lc WHERE lc.id = ec.id
          )
        """
    )
