"""Finance approvals, procurement, transition tasks, renewal deadlines, import batches.

Adds the controls a competitive bid is evaluated on:

* maker-checker approval state on every postable finance document
* a procurement chain (requisition -> competing bids -> purchase order -> receipt)
  plus the purchase-order link that enables a three-way match on vendor bills
* accountability fields on transition checklist items
* ownership and notice evidence on lease renewals and options
* import batches, which give bulk loads replay protection and an audit trail

Revision ID: 123
Revises: 122
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "123"
down_revision = "122"
branch_labels = None
depends_on = None

_PREDICATE = """(
    current_setting('app.rls_bypass', true) = 'on'
    OR organization_id = NULLIF(current_setting('app.current_org', true), '')::uuid
)"""

# Finance and procurement documents carry money, so they get the same
# row-level tenant isolation as the rest of the high-risk tables.
_RLS_TABLES = ("purchase_requisitions", "purchase_orders", "import_batches")

# Approval columns are identical everywhere; applied by loop below.
_APPROVAL_TABLES = ("vendor_bills", "customer_invoices", "cam_reconciliations")


def _enable_rls(table: str) -> None:
    op.execute(f'DROP POLICY IF EXISTS "{table}_org_isolation" ON "{table}"')
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_org_isolation ON {table} "
        f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
    )


def _add_approval_columns(table: str) -> None:
    op.add_column(
        table,
        sa.Column(
            "approval_status",
            sa.String(20),
            nullable=False,
            server_default="not_required",
        ),
    )
    op.add_column(table, sa.Column("prepared_by_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(table, sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(table, sa.Column("submitted_by_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(table, sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(table, sa.Column("approved_by_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(table, sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(table, sa.Column("rejected_by_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(table, sa.Column("rejection_reason", sa.Text(), nullable=True))
    op.add_column(
        table, sa.Column("approval_threshold_applied", sa.String(32), nullable=True)
    )
    for column in (
        "prepared_by_id",
        "submitted_by_id",
        "approved_by_id",
        "rejected_by_id",
    ):
        op.create_foreign_key(
            f"fk_{table}_{column}_users", table, "users", [column], ["id"]
        )
    op.create_index(f"idx_{table}_approval_status", table, ["approval_status"])


def upgrade() -> None:
    # ── Organization-level policy ────────────────────────────────────────────
    op.add_column(
        "organizations",
        sa.Column(
            "finance_approval_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "finance_approval_threshold",
            sa.Numeric(15, 2),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "procurement_bid_threshold",
            sa.Numeric(15, 2),
            nullable=False,
            server_default="5000",
        ),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "procurement_required_bids",
            sa.Integer(),
            nullable=False,
            server_default="3",
        ),
    )

    # ── Maker-checker on postable finance documents ──────────────────────────
    for table in _APPROVAL_TABLES:
        _add_approval_columns(table)

    # ── Procurement ──────────────────────────────────────────────────────────
    op.create_table(
        "purchase_requisitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("requisition_number", sa.String(50), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("office_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("offices.id", ondelete="SET NULL"), nullable=True),
        sa.Column("category", sa.String(60), nullable=True),
        sa.Column("needed_by", sa.Date(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("estimated_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("requested_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("ordered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_status", sa.String(20), nullable=False, server_default="not_required"),
        sa.Column("prepared_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("approval_threshold_applied", sa.String(32), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_purchase_requisitions_org", "purchase_requisitions", ["organization_id"])
    op.create_index("idx_purchase_requisitions_status", "purchase_requisitions", ["status"])
    op.create_index("idx_purchase_requisitions_office", "purchase_requisitions", ["office_id"])

    op.create_table(
        "requisition_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("requisition_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("purchase_requisitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("quantity", sa.Numeric(15, 2), nullable=False, server_default="1"),
        sa.Column("unit_price", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("gl_accounts.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_requisition_lines_req", "requisition_lines", ["requisition_id"])

    op.create_table(
        "vendor_quotes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("requisition_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("purchase_requisitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("quote_date", sa.Date(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("reference", sa.String(100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_selected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("selection_reason", sa.Text(), nullable=True),
        sa.Column("selected_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_vendor_quotes_req", "vendor_quotes", ["requisition_id"])
    op.create_index("idx_vendor_quotes_vendor", "vendor_quotes", ["vendor_id"])

    op.create_table(
        "purchase_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("requisition_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("purchase_requisitions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("vendor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("po_number", sa.String(50), nullable=True),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("expected_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(25), nullable=False, server_default="issued"),
        sa.Column("total_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("match_tolerance_percent", sa.Numeric(5, 2), nullable=False, server_default="5"),
        sa.Column("memo", sa.Text(), nullable=True),
        sa.Column("issued_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_purchase_orders_org", "purchase_orders", ["organization_id"])
    op.create_index("idx_purchase_orders_vendor", "purchase_orders", ["vendor_id"])
    op.create_index("idx_purchase_orders_number", "purchase_orders", ["po_number"])

    op.create_table(
        "purchase_order_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("purchase_order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("quantity", sa.Numeric(15, 2), nullable=False, server_default="1"),
        sa.Column("unit_price", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("quantity_received", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("gl_accounts.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_po_lines_order", "purchase_order_lines", ["purchase_order_id"])

    op.create_table(
        "purchase_order_receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("purchase_order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("received_on", sa.Date(), nullable=False),
        sa.Column("received_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_po_receipts_order", "purchase_order_receipts", ["purchase_order_id"])

    op.create_table(
        "purchase_order_receipt_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("receipt_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("purchase_order_receipts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("purchase_order_line_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("purchase_order_lines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("quantity", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_po_receipt_lines_receipt", "purchase_order_receipt_lines", ["receipt_id"])
    op.create_index("idx_po_receipt_lines_line", "purchase_order_receipt_lines", ["purchase_order_line_id"])

    # Three-way match link from an invoice back to the order it settles.
    op.add_column(
        "vendor_bills",
        sa.Column("purchase_order_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_vendor_bills_purchase_order",
        "vendor_bills",
        "purchase_orders",
        ["purchase_order_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_vendor_bills_po", "vendor_bills", ["purchase_order_id"])

    # ── Transition checklist accountability ──────────────────────────────────
    op.add_column("transition_checklist_items", sa.Column("assigned_to_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("transition_checklist_items", sa.Column("due_date", sa.Date(), nullable=True))
    op.add_column("transition_checklist_items", sa.Column("vendor_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("transition_checklist_items", sa.Column("depends_on_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("transition_checklist_items", sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("transition_checklist_items", sa.Column("requires_evidence", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("transition_checklist_items", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("transition_checklist_items", sa.Column("completed_by_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("transition_checklist_items", sa.Column("last_reminded_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_tci_assigned_to", "transition_checklist_items", "users", ["assigned_to_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_tci_completed_by", "transition_checklist_items", "users", ["completed_by_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_tci_vendor", "transition_checklist_items", "vendors", ["vendor_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_tci_depends_on", "transition_checklist_items", "transition_checklist_items", ["depends_on_id"], ["id"], ondelete="SET NULL")
    op.create_index("idx_tci_assigned_to", "transition_checklist_items", ["assigned_to_id"])

    # ── Renewal / option ownership and evidence ──────────────────────────────
    op.add_column("lease_renewals", sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("lease_renewals", sa.Column("notice_due_date", sa.Date(), nullable=True))
    op.add_column("lease_renewals", sa.Column("auto_opened", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("lease_renewals", sa.Column("last_reminded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("lease_renewals", sa.Column("notice_method", sa.String(40), nullable=True))
    op.add_column("lease_renewals", sa.Column("notice_reference", sa.String(255), nullable=True))
    op.create_foreign_key("fk_lease_renewals_owner", "lease_renewals", "users", ["owner_id"], ["id"], ondelete="SET NULL")
    op.create_index("idx_lease_renewals_owner", "lease_renewals", ["owner_id"])

    op.add_column("lease_options", sa.Column("exercised_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("lease_options", sa.Column("exercised_by_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("lease_options", sa.Column("renewal_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("lease_options", sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("lease_options", sa.Column("last_reminded_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_lease_options_exercised_by", "lease_options", "users", ["exercised_by_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_lease_options_owner", "lease_options", "users", ["owner_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_lease_options_renewal", "lease_options", "lease_renewals", ["renewal_id"], ["id"], ondelete="SET NULL")
    op.create_index("idx_lease_options_owner", "lease_options", ["owner_id"])

    # ── Import batches ───────────────────────────────────────────────────────
    op.create_table(
        "import_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("entity_type", sa.String(60), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("rows_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("row_errors", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("imported_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_import_batches_org", "import_batches", ["organization_id"])
    op.create_index("idx_import_batches_entity", "import_batches", ["entity_type"])
    # Replay detection looks up org + hash, so index the pair.
    op.create_index("idx_import_batches_hash", "import_batches", ["organization_id", "content_hash"])

    for table in _RLS_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    for table in _RLS_TABLES:
        op.execute(f'DROP POLICY IF EXISTS "{table}_org_isolation" ON "{table}"')

    op.drop_table("import_batches")

    op.drop_constraint("fk_lease_options_renewal", "lease_options", type_="foreignkey")
    op.drop_constraint("fk_lease_options_owner", "lease_options", type_="foreignkey")
    op.drop_constraint("fk_lease_options_exercised_by", "lease_options", type_="foreignkey")
    op.drop_index("idx_lease_options_owner", table_name="lease_options")
    for column in ("last_reminded_at", "owner_id", "renewal_id", "exercised_by_id", "exercised_at"):
        op.drop_column("lease_options", column)

    op.drop_index("idx_lease_renewals_owner", table_name="lease_renewals")
    op.drop_constraint("fk_lease_renewals_owner", "lease_renewals", type_="foreignkey")
    for column in ("notice_reference", "notice_method", "last_reminded_at", "auto_opened", "notice_due_date", "owner_id"):
        op.drop_column("lease_renewals", column)

    op.drop_index("idx_tci_assigned_to", table_name="transition_checklist_items")
    for constraint in ("fk_tci_depends_on", "fk_tci_vendor", "fk_tci_completed_by", "fk_tci_assigned_to"):
        op.drop_constraint(constraint, "transition_checklist_items", type_="foreignkey")
    for column in (
        "last_reminded_at", "completed_by_id", "completed_at", "requires_evidence",
        "is_required", "depends_on_id", "vendor_id", "due_date", "assigned_to_id",
    ):
        op.drop_column("transition_checklist_items", column)

    op.drop_index("idx_vendor_bills_po", table_name="vendor_bills")
    op.drop_constraint("fk_vendor_bills_purchase_order", "vendor_bills", type_="foreignkey")
    op.drop_column("vendor_bills", "purchase_order_id")

    op.drop_table("purchase_order_receipt_lines")
    op.drop_table("purchase_order_receipts")
    op.drop_table("purchase_order_lines")
    op.drop_table("purchase_orders")
    op.drop_table("vendor_quotes")
    op.drop_table("requisition_lines")
    op.drop_table("purchase_requisitions")

    for table in _APPROVAL_TABLES:
        op.drop_index(f"idx_{table}_approval_status", table_name=table)
        for column in ("prepared_by_id", "submitted_by_id", "approved_by_id", "rejected_by_id"):
            op.drop_constraint(f"fk_{table}_{column}_users", table, type_="foreignkey")
        for column in (
            "approval_threshold_applied", "rejection_reason", "rejected_by_id", "rejected_at",
            "approved_by_id", "approved_at", "submitted_by_id", "submitted_at",
            "prepared_by_id", "approval_status",
        ):
            op.drop_column(table, column)

    for column in (
        "procurement_required_bids",
        "procurement_bid_threshold",
        "finance_approval_threshold",
        "finance_approval_enabled",
    ):
        op.drop_column("organizations", column)
