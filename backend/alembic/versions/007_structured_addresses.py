"""add structured address columns to landlords and vendors

Revision ID: 007
Revises: 006
Create Date: 2026-04-26

This migration adds structured address columns (address_line_1, address_line_2,
city, state, zip_code) to the landlords and vendors tables. The legacy
`address` (and `contact_mailing_address` for landlords) columns are KEPT
intact so existing data is never lost.

A best-effort parser is run during upgrade to back-fill the new structured
columns from the existing free-form text. Records that don't match a common
US-address pattern simply keep the legacy text-only address and the
structured fields stay NULL — the application reads both and falls back to
the legacy field when structured values are missing.
"""

import re

from alembic import op
import sqlalchemy as sa


revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def _existing_columns(table: str) -> set[str]:
    """Return the set of column names currently present on `table`."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {c["name"] for c in inspector.get_columns(table)}


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    """
    Idempotent `op.add_column`. No-ops when the column is already present.

    Necessary because earlier deployments of this app called
    `Base.metadata.create_all()` directly with the up-to-date ORM models,
    which can leave a database in a state where some of the columns this
    migration is supposed to add already exist.
    """
    if column.name in _existing_columns(table):
        return
    op.add_column(table, column)


def _drop_column_if_present(table: str, column_name: str) -> None:
    if column_name in _existing_columns(table):
        op.drop_column(table, column_name)


# ── Address parser ───────────────────────────────────────────────────────────
#
# Recognises a few common US-address patterns:
#   123 Main St, Anytown, NY 10001
#   123 Main St
#   Anytown, NY 10001
#   123 Main St\nAnytown, NY 10001
#   123 Main St, Apt 4B, Anytown, NY 10001
#
# Returns a tuple of (line1, line2, city, state, zip). Any field that
# cannot be confidently determined is None — the caller must keep the
# original free-form string available as a fallback.

# State + zip together at the END of the string are the strongest anchor.
# Matches "NY 10001" or "NY 10001-1234".
_STATE_ZIP_RE = re.compile(r"\b([A-Z]{2})\s+(\d{5}(?:-\d{4})?)\s*$")


def parse_us_address(raw: str | None):
    if not raw:
        return None, None, None, None, None

    # Normalize whitespace: replace newlines with commas, collapse runs.
    text = raw.replace("\r", "").replace("\n", ", ").strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r",\s*,+", ",", text).strip(", ")

    # Try to find "<state> <zip>" at the end.
    m = _STATE_ZIP_RE.search(text)
    state = zip_code = None
    if m:
        state, zip_code = m.group(1), m.group(2)
        text = text[: m.start()].rstrip(", ").strip()

    # Whatever's left should be: <line1>[, <line2>][, <city>]
    parts = [p.strip() for p in text.split(",") if p.strip()]
    line1 = line2 = city = None

    if state and parts:
        # If state was found, the last comma-separated token is the city.
        city = parts.pop()
    if parts:
        line1 = parts.pop(0)
    if parts:
        # Anything else collapses into line2 (handles "Apt 4B" + extras).
        line2 = ", ".join(parts) or None

    # Sanity caps so we don't try to stuff novels into VARCHAR(255).
    def _cap(s, n):
        if s is None:
            return None
        s = s.strip()
        return s[:n] if s else None

    return (
        _cap(line1, 255),
        _cap(line2, 255),
        _cap(city, 100),
        _cap(state, 2),
        _cap(zip_code, 10),
    )


# ── Schema changes ───────────────────────────────────────────────────────────


def upgrade() -> None:
    # ----- vendors -----
    _add_column_if_missing("vendors", sa.Column("address_line_1", sa.String(255), nullable=True))
    _add_column_if_missing("vendors", sa.Column("address_line_2", sa.String(255), nullable=True))
    _add_column_if_missing("vendors", sa.Column("city", sa.String(100), nullable=True))
    _add_column_if_missing("vendors", sa.Column("state", sa.String(2), nullable=True))
    _add_column_if_missing("vendors", sa.Column("zip_code", sa.String(10), nullable=True))

    # ----- landlords (property + mailing) -----
    _add_column_if_missing("landlords", sa.Column("address_line_1", sa.String(255), nullable=True))
    _add_column_if_missing("landlords", sa.Column("address_line_2", sa.String(255), nullable=True))
    _add_column_if_missing("landlords", sa.Column("city", sa.String(100), nullable=True))
    _add_column_if_missing("landlords", sa.Column("state", sa.String(2), nullable=True))
    _add_column_if_missing("landlords", sa.Column("zip_code", sa.String(10), nullable=True))
    _add_column_if_missing("landlords", sa.Column("mailing_address_line_1", sa.String(255), nullable=True))
    _add_column_if_missing("landlords", sa.Column("mailing_address_line_2", sa.String(255), nullable=True))
    _add_column_if_missing("landlords", sa.Column("mailing_city", sa.String(100), nullable=True))
    _add_column_if_missing("landlords", sa.Column("mailing_state", sa.String(2), nullable=True))
    _add_column_if_missing("landlords", sa.Column("mailing_zip_code", sa.String(10), nullable=True))

    # ----- backfill from legacy free-form text -----
    bind = op.get_bind()

    # Vendors
    rows = bind.execute(sa.text("SELECT id, address FROM vendors WHERE address IS NOT NULL")).fetchall()
    for row in rows:
        line1, line2, city, state, zip_code = parse_us_address(row.address)
        if any([line1, city, state, zip_code]):
            bind.execute(
                sa.text(
                    """
                    UPDATE vendors
                       SET address_line_1 = :l1,
                           address_line_2 = :l2,
                           city = :city,
                           state = :state,
                           zip_code = :zip
                     WHERE id = :id
                    """
                ),
                {"l1": line1, "l2": line2, "city": city, "state": state, "zip": zip_code, "id": row.id},
            )

    # Landlords - property address
    rows = bind.execute(sa.text("SELECT id, address FROM landlords WHERE address IS NOT NULL")).fetchall()
    for row in rows:
        line1, line2, city, state, zip_code = parse_us_address(row.address)
        if any([line1, city, state, zip_code]):
            bind.execute(
                sa.text(
                    """
                    UPDATE landlords
                       SET address_line_1 = :l1,
                           address_line_2 = :l2,
                           city = :city,
                           state = :state,
                           zip_code = :zip
                     WHERE id = :id
                    """
                ),
                {"l1": line1, "l2": line2, "city": city, "state": state, "zip": zip_code, "id": row.id},
            )

    # Landlords - mailing address
    rows = bind.execute(
        sa.text("SELECT id, contact_mailing_address FROM landlords WHERE contact_mailing_address IS NOT NULL")
    ).fetchall()
    for row in rows:
        line1, line2, city, state, zip_code = parse_us_address(row.contact_mailing_address)
        if any([line1, city, state, zip_code]):
            bind.execute(
                sa.text(
                    """
                    UPDATE landlords
                       SET mailing_address_line_1 = :l1,
                           mailing_address_line_2 = :l2,
                           mailing_city = :city,
                           mailing_state = :state,
                           mailing_zip_code = :zip
                     WHERE id = :id
                    """
                ),
                {"l1": line1, "l2": line2, "city": city, "state": state, "zip": zip_code, "id": row.id},
            )


def downgrade() -> None:
    # Drop new columns. Legacy `address` / `contact_mailing_address` are
    # untouched so no data is lost on downgrade.
    for col in (
        "mailing_zip_code",
        "mailing_state",
        "mailing_city",
        "mailing_address_line_2",
        "mailing_address_line_1",
        "zip_code",
        "state",
        "city",
        "address_line_2",
        "address_line_1",
    ):
        _drop_column_if_present("landlords", col)

    for col in ("zip_code", "state", "city", "address_line_2", "address_line_1"):
        _drop_column_if_present("vendors", col)
