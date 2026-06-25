"""add missing indexes

Revision ID: 001_add_indexes
Revises:
Create Date: 2026-04-23
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("idx_landlords_office_id", "landlords", ["office_id"])
    op.create_index("idx_landlords_ern", "landlords", ["ern"])
    op.create_index("idx_hvac_contracts_office_id", "hvac_contracts", ["office_id"])
    op.create_index("idx_hvac_contracts_manager_id", "hvac_contracts", ["manager_id"])
    op.create_index("idx_activity_log_user_id", "activity_log", ["user_id"])
    op.create_index("idx_maint_ticket_created", "maintenance_tickets", ["created_at"])
    op.create_index("idx_leases_office_id", "leases", ["office_id"])
    op.create_index("idx_leases_manager_id", "leases", ["manager_id"])


def downgrade() -> None:
    op.drop_index("idx_leases_manager_id", table_name="leases")
    op.drop_index("idx_leases_office_id", table_name="leases")
    op.drop_index("idx_maint_ticket_created", table_name="maintenance_tickets")
    op.drop_index("idx_activity_log_user_id", table_name="activity_log")
    op.drop_index("idx_hvac_contracts_manager_id", table_name="hvac_contracts")
    op.drop_index("idx_hvac_contracts_office_id", table_name="hvac_contracts")
    op.drop_index("idx_landlords_ern", table_name="landlords")
    op.drop_index("idx_landlords_office_id", table_name="landlords")
