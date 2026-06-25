"""Lease Abstract clause-category catalog.

Defines the canonical set of lease-abstract clause categories rendered in the
Lease Abstract grid (modelled on the Quarem Vantage "Lease Abstract" screen).

Each category has:
  - ``key``    — stable identifier persisted on ``lease_abstract_clauses`` rows.
  - ``name``   — display label shown in the grid.
  - ``group``  — column the card is rendered in (``financial`` / ``clauses`` /
                 ``rights``).
  - ``order``  — display order within its group.
  - ``fields`` — ordered field schema captured for that clause. Each field is a
                 ``{key, label, type, options?}`` dict where ``type`` is one of
                 ``text`` / ``textarea`` / ``date`` / ``currency`` / ``number`` /
                 ``percent`` / ``boolean`` / ``select``.

The catalog is the single source of truth for both the API (which merges stored
content onto it) and the frontend grid. It is intentionally code-defined so it
stays in lock-step with the schema validation, while still being served to the
client so the UI renders dynamically.
"""
from __future__ import annotations

# Valid field input types for clause schemas.
FIELD_TYPES = {
    "text",
    "textarea",
    "date",
    "currency",
    "number",
    "percent",
    "boolean",
    "select",
}

# Valid completeness statuses for a clause.
CLAUSE_STATUSES = {"contains_content", "needs_content", "incomplete"}
DEFAULT_STATUS = "needs_content"


def _f(key: str, label: str, ftype: str = "text", options: list[str] | None = None) -> dict:
    field: dict = {"key": key, "label": label, "type": ftype}
    if options is not None:
        field["options"] = options
    return field


# A shared "summary" + "notes" tail appended to most clauses so every category
# can always capture narrative content even when it has no bespoke fields.
def _summary(*extra: dict) -> list[dict]:
    return [_f("summary", "Summary", "textarea"), *extra, _f("notes", "Notes", "textarea")]


CLAUSE_CATEGORIES: list[dict] = [
    # ── Financial / space column ──────────────────────────────────────────
    {
        "key": "square_footage",
        "name": "Square Footage Information",
        "group": "financial",
        "order": 10,
        "fields": [
            _f("rentable_sf", "Rentable SF", "number"),
            _f("usable_sf", "Usable SF", "number"),
            _f("load_factor", "Load Factor %", "percent"),
            _f("measurement_standard", "Measurement Standard"),
            *_summary(),
        ],
    },
    {
        "key": "rent_expiration",
        "name": "Rent/Expiration",
        "group": "financial",
        "order": 20,
        "fields": [
            _f("base_rent", "Base Rent", "currency"),
            _f("rent_frequency", "Rent Frequency", "select", ["monthly", "quarterly", "annually"]),
            _f("commencement_date", "Commencement Date", "date"),
            _f("expiration_date", "Expiration Date", "date"),
            _f("annual_escalation", "Annual Escalation %", "percent"),
            *_summary(),
        ],
    },
    {
        "key": "expense_schedule",
        "name": "Expense Schedule",
        "group": "financial",
        "order": 30,
        "fields": [
            _f("expense_type", "Expense Type", "select", ["net", "gross", "modified_gross", "base_year", "expense_stop"]),
            _f("base_year", "Base Year", "number"),
            _f("expense_stop", "Expense Stop", "currency"),
            *_summary(),
        ],
    },
    {
        "key": "expense_recoverables",
        "name": "Expense/Recoverables",
        "group": "financial",
        "order": 40,
        "fields": [
            _f("recoverable_expenses", "Recoverable Expenses", "textarea"),
            _f("pro_rata_share", "Pro-Rata Share %", "percent"),
            _f("cap_on_increases", "Cap on Increases %", "percent"),
            _f("gross_up_percentage", "Gross-Up %", "percent"),
            *_summary(),
        ],
    },
    {
        "key": "cpi",
        "name": "Consumer Price Index (CPI)",
        "group": "financial",
        "order": 50,
        "fields": [
            _f("cpi_applies", "CPI Adjustment Applies", "boolean"),
            _f("cpi_index", "CPI Index"),
            _f("cpi_floor", "Floor %", "percent"),
            _f("cpi_ceiling", "Ceiling %", "percent"),
            *_summary(),
        ],
    },
    {
        "key": "improvements",
        "name": "Improvements",
        "group": "financial",
        "order": 60,
        "fields": [
            _f("ti_allowance", "TI Allowance", "currency"),
            _f("ti_allowance_psf", "TI Allowance / SF", "currency"),
            _f("responsible_party", "Responsible Party", "select", ["landlord", "tenant", "shared"]),
            *_summary(),
        ],
    },
    # ── Clauses column ────────────────────────────────────────────────────
    {
        "key": "force_majeure",
        "name": "Force Majeure",
        "group": "clauses",
        "order": 10,
        "fields": _summary(),
    },
    {
        "key": "lease_options",
        "name": "Lease Options",
        "group": "clauses",
        "order": 20,
        "fields": [
            _f("option_type", "Option Type", "select", ["renewal", "expansion", "termination", "purchase", "rofr", "rofo"]),
            _f("exercise_window_start", "Exercise Window Start", "date"),
            _f("exercise_window_end", "Exercise Window End", "date"),
            _f("notice_required_days", "Notice Required (days)", "number"),
            *_summary(),
        ],
    },
    {
        "key": "signage_exclusivity",
        "name": "Signage/Exclusivity",
        "group": "clauses",
        "order": 30,
        "fields": _summary(),
    },
    {
        "key": "relocation_right",
        "name": "Relocation Right",
        "group": "clauses",
        "order": 40,
        "fields": [
            _f("landlord_may_relocate", "Landlord May Relocate", "boolean"),
            _f("relocation_notice_days", "Relocation Notice (days)", "number"),
            *_summary(),
        ],
    },
    {
        "key": "holdover",
        "name": "Holdover",
        "group": "clauses",
        "order": 50,
        "fields": [
            _f("holdover_rate", "Holdover Rate %", "percent"),
            _f("holdover_basis", "Holdover Basis", "select", ["base_rent", "fair_market", "fixed"]),
            *_summary(),
        ],
    },
    {
        "key": "late_fees",
        "name": "Late Fees",
        "group": "clauses",
        "order": 60,
        "fields": [
            _f("late_fee_amount", "Late Fee Amount", "currency"),
            _f("late_fee_percent", "Late Fee %", "percent"),
            _f("grace_period_days", "Grace Period (days)", "number"),
            *_summary(),
        ],
    },
    {
        "key": "interest",
        "name": "Interest",
        "group": "clauses",
        "order": 70,
        "fields": [
            _f("default_interest_rate", "Default Interest Rate %", "percent"),
            *_summary(),
        ],
    },
    {
        "key": "brokerage_fees",
        "name": "Brokerage Fees",
        "group": "clauses",
        "order": 80,
        "fields": [
            _f("broker_name", "Broker Name"),
            _f("commission_amount", "Commission Amount", "currency"),
            _f("commission_percent", "Commission %", "percent"),
            _f("paid_by", "Paid By", "select", ["landlord", "tenant", "shared"]),
            *_summary(),
        ],
    },
    {
        "key": "landlord_restriction",
        "name": "Landlord Restriction",
        "group": "clauses",
        "order": 90,
        "fields": _summary(),
    },
    {
        "key": "indemnification",
        "name": "Indemnification",
        "group": "clauses",
        "order": 100,
        "fields": _summary(),
    },
    {
        "key": "rooftop_telecom_antenna",
        "name": "Rooftop/Telecom/Antenna",
        "group": "clauses",
        "order": 110,
        "fields": _summary(),
    },
    {
        "key": "go_dark_co_tenancy",
        "name": "Go Dark / Co-Tenancy",
        "group": "clauses",
        "order": 120,
        "fields": _summary(),
    },
    {
        "key": "asc842_ifrs16_elections",
        "name": "ASC 842 / IFRS 16 Elections",
        "group": "clauses",
        "order": 130,
        "fields": [
            _f("accounting_standard", "Accounting Standard", "select", ["asc842", "ifrs16", "both"]),
            _f("lease_classification", "Classification", "select", ["operating", "finance"]),
            _f("short_term_exemption", "Short-Term Exemption", "boolean"),
            _f("low_value_exemption", "Low-Value Exemption", "boolean"),
            *_summary(),
        ],
    },
    {
        "key": "notices",
        "name": "Notices",
        "group": "clauses",
        "order": 140,
        "fields": [
            _f("landlord_notice_address", "Landlord Notice Address", "textarea"),
            _f("tenant_notice_address", "Tenant Notice Address", "textarea"),
            _f("delivery_method", "Delivery Method", "select", ["certified_mail", "overnight_courier", "personal", "email"]),
            *_summary(),
        ],
    },
    # ── Rights column ─────────────────────────────────────────────────────
    {
        "key": "surrender_restoration",
        "name": "Surrender/Restoration",
        "group": "rights",
        "order": 10,
        "fields": _summary(),
    },
    {
        "key": "security_deposit",
        "name": "Security Deposit",
        "group": "rights",
        "order": 20,
        "fields": [
            _f("deposit_amount", "Deposit Amount", "currency"),
            _f("deposit_type", "Deposit Type", "select", ["cash", "letter_of_credit", "guarantee"]),
            _f("burndown", "Burndown / Reduction", "textarea"),
            _f("return_terms", "Return Terms", "textarea"),
            *_summary(),
        ],
    },
    {
        "key": "exclusivity_permitted_use",
        "name": "Exclusivity/ Permitted Use",
        "group": "rights",
        "order": 30,
        "fields": [
            _f("permitted_use", "Permitted Use", "textarea"),
            _f("exclusive_use", "Exclusive Use", "textarea"),
            *_summary(),
        ],
    },
    {
        "key": "insurance",
        "name": "Insurance",
        "group": "rights",
        "order": 40,
        "fields": [
            _f("liability_coverage", "Liability Coverage", "currency"),
            _f("property_coverage", "Property Coverage", "currency"),
            _f("waiver_of_subrogation", "Waiver of Subrogation", "boolean"),
            *_summary(),
        ],
    },
    {
        "key": "estoppel_snda",
        "name": "Estoppel/Subordination/Non-Disturbance",
        "group": "rights",
        "order": 50,
        "fields": [
            _f("estoppel_response_days", "Estoppel Response (days)", "number"),
            _f("snda_required", "SNDA Required", "boolean"),
            *_summary(),
        ],
    },
    {
        "key": "sublease_assignment",
        "name": "Sublease/Assignment",
        "group": "rights",
        "order": 60,
        "fields": [
            _f("consent_required", "Landlord Consent Required", "boolean"),
            _f("consent_standard", "Consent Standard", "select", ["sole_discretion", "reasonable", "no_consent"]),
            _f("profit_sharing_percent", "Profit Sharing %", "percent"),
            *_summary(),
        ],
    },
    {
        "key": "lease_audit_rights",
        "name": "Lease Audit Rights",
        "group": "rights",
        "order": 70,
        "fields": [
            _f("audit_window_days", "Audit Window (days)", "number"),
            _f("audit_cost_threshold", "Cost-Shift Threshold %", "percent"),
            *_summary(),
        ],
    },
    {
        "key": "hvac_additional_usage",
        "name": "HVAC/ Additional Usage",
        "group": "rights",
        "order": 80,
        "fields": [
            _f("hvac_hours", "Standard HVAC Hours"),
            _f("after_hours_rate", "After-Hours Rate", "currency"),
            *_summary(),
        ],
    },
    {
        "key": "sublease_information",
        "name": "Sublease Information",
        "group": "rights",
        "order": 90,
        "fields": [
            _f("subtenant_name", "Subtenant Name"),
            _f("sublease_sf", "Sublease SF", "number"),
            _f("sublease_rent", "Sublease Rent", "currency"),
            *_summary(),
        ],
    },
    {
        "key": "rea",
        "name": "Reciprocal Easement Agreement(REA)",
        "group": "rights",
        "order": 100,
        "fields": _summary(),
    },
    {
        "key": "maintenance_repairs",
        "name": "Maintenance and Repairs",
        "group": "rights",
        "order": 110,
        "fields": [
            _f("landlord_obligations", "Landlord Obligations", "textarea"),
            _f("tenant_obligations", "Tenant Obligations", "textarea"),
            *_summary(),
        ],
    },
    {
        "key": "hazardous_materials",
        "name": "Hazardous Materials",
        "group": "rights",
        "order": 120,
        "fields": _summary(),
    },
    {
        "key": "utilities_services",
        "name": "Utilities and Services",
        "group": "rights",
        "order": 130,
        "fields": [
            _f("metering", "Metering", "select", ["separately_metered", "submetered", "included"]),
            _f("services_provided", "Services Provided", "textarea"),
            *_summary(),
        ],
    },
    {
        "key": "other_critical_issues",
        "name": "Other Critical Issues",
        "group": "rights",
        "order": 140,
        "fields": _summary(),
    },
]

# Fast lookups.
CATEGORY_BY_KEY: dict[str, dict] = {c["key"]: c for c in CLAUSE_CATEGORIES}
CATEGORY_KEYS: set[str] = set(CATEGORY_BY_KEY)


def get_category(key: str) -> dict | None:
    """Return the catalog entry for ``key`` or ``None`` if unknown."""
    return CATEGORY_BY_KEY.get(key)


def content_field_keys(category: dict) -> list[str]:
    """Return the field keys for a category (used for completeness checks)."""
    return [f["key"] for f in category["fields"]]


def derive_status(category: dict, content: dict | None, notes: str | None) -> str:
    """Auto-derive a completeness status from stored content.

    - ``needs_content``    — nothing captured at all.
    - ``contains_content`` — every field in the schema has a value.
    - ``incomplete``       — some, but not all, fields captured.
    """
    field_keys = content_field_keys(category)
    content = content or {}
    filled = [
        k
        for k in field_keys
        if k in content and content[k] not in (None, "", [], {})
    ]
    has_notes = bool(notes and notes.strip())
    if not filled and not has_notes:
        return "needs_content"
    if len(filled) == len(field_keys):
        return "contains_content"
    return "incomplete"
