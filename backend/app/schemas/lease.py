import uuid
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, field_validator
from app.schemas.office import ManagerResponse
from app.utils.currency import normalize_currency_code


class OfficeSlimResponse(BaseModel):
    id: uuid.UUID
    location_name: str
    office_number: int

    model_config = {"from_attributes": True}


class LeaseNoteCreate(BaseModel):
    note_text: str


class LeaseNoteResponse(BaseModel):
    id: uuid.UUID
    note_text: str
    note_order: int
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Shared accounting fields mixin ---

# Accepted code values for the short, length-bounded enum-style columns. Free
# text (e.g. AI-extracted "ASC 842 / IFRS 16") that does not match is coerced to
# None rather than allowed to overflow the column and 500 the request.
_ACCOUNTING_STANDARDS = {"asc842", "ifrs16", "both"}
_LEASE_CLASSIFICATIONS = {"operating", "finance"}
_PAYMENT_FREQUENCIES = {"monthly", "quarterly", "annually"}


def _coerce_enum(value: object, allowed: set[str]) -> str | None:
    """Lower-case and validate against ``allowed``; return None when invalid."""
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized if normalized in allowed else None


def _cap_length(value: object, max_length: int) -> str | None:
    """Trim a free-text value to ``max_length`` chars so it fits its column.

    AI-extracted or free-text values can exceed the underlying varchar limit and
    cause a database StringDataRightTruncation (HTTP 500). Capping keeps the
    lease create/update path resilient while preserving the leading content.
    """
    if value is None:
        return None
    text = str(value)
    return text[:max_length]


class _LeaseAccountingFields(BaseModel):
    lease_commencement_date: date | None = None
    accounting_standard: str | None = None          # 'asc842' | 'ifrs16' | 'both'
    lease_classification: str | None = None         # 'operating' | 'finance'
    payment_amount: Decimal | None = None
    payment_frequency: str | None = None            # 'monthly' | 'quarterly' | 'annually'
    annual_escalation_rate: Decimal | None = None   # e.g. 0.030000 = 3 %
    incremental_borrowing_rate: Decimal | None = None  # e.g. 0.045000 = 4.5 %
    initial_direct_costs: Decimal | None = None
    lease_incentives: Decimal | None = None
    prepaid_rent: Decimal | None = None
    residual_value_guarantee: Decimal | None = None
    is_short_term_lease: bool = False
    is_low_value_lease: bool = False
    currency: str | None = "USD"

    @field_validator("currency", mode="before")
    @classmethod
    def _normalize_currency(cls, value: object) -> str | None:
        # Coerce free-text / AI-extracted currency (e.g. "US Dollars") to a
        # 3-letter code so it can never overflow the varchar(3) column and
        # 500 the lease create/update request.
        if value is None:
            return None
        return normalize_currency_code(str(value))

    @field_validator("accounting_standard", mode="before")
    @classmethod
    def _normalize_accounting_standard(cls, value: object) -> str | None:
        return _coerce_enum(value, _ACCOUNTING_STANDARDS)

    @field_validator("lease_classification", mode="before")
    @classmethod
    def _normalize_lease_classification(cls, value: object) -> str | None:
        return _coerce_enum(value, _LEASE_CLASSIFICATIONS)

    @field_validator("payment_frequency", mode="before")
    @classmethod
    def _normalize_payment_frequency(cls, value: object) -> str | None:
        return _coerce_enum(value, _PAYMENT_FREQUENCIES)


class _LeaseBoundedTextMixin(BaseModel):
    """Caps free-text fields backed by length-bounded varchar columns.

    AI-extracted values (e.g. a full notice clause pasted into ``notice_period``)
    can exceed the column limit and raise a database StringDataRightTruncation
    (HTTP 500) on create/update. Capping keeps the request resilient.
    """

    @field_validator("lease_name", mode="before", check_fields=False)
    @classmethod
    def _cap_lease_name(cls, value: object) -> object:
        return _cap_length(value, 255)

    @field_validator("notice_period", mode="before", check_fields=False)
    @classmethod
    def _cap_notice_period(cls, value: object) -> object:
        return _cap_length(value, 255)


class LeaseCreate(_LeaseAccountingFields, _LeaseBoundedTextMixin):
    office_id: uuid.UUID | None = None
    lease_name: str
    manager_id: uuid.UUID | None = None
    lease_expiration: date | None = None
    lessor_name: str | None = None
    notice_period: str | None = None
    notice_period_days: int | None = None
    lease_notice_date: date | None = None
    notice_given_date: date | None = None
    quarem_date: date | None = None
    quarem_status: str | None = None
    expiration_year: int


class LeaseUpdate(_LeaseAccountingFields, _LeaseBoundedTextMixin):
    office_id: uuid.UUID | None = None
    lease_name: str | None = None
    manager_id: uuid.UUID | None = None
    lease_expiration: date | None = None
    lessor_name: str | None = None
    notice_period: str | None = None
    notice_period_days: int | None = None
    lease_notice_date: date | None = None
    notice_given_date: date | None = None
    quarem_date: date | None = None
    quarem_status: str | None = None
    expiration_year: int | None = None


class LeaseResponse(_LeaseAccountingFields):
    id: uuid.UUID
    office_id: uuid.UUID | None
    office: OfficeSlimResponse | None = None
    lease_name: str
    manager: ManagerResponse | None
    lease_expiration: date | None
    lessor_name: str | None
    notice_period: str | None
    notice_period_days: int | None
    lease_notice_date: date | None
    notice_given_date: date | None
    quarem_date: date | None
    quarem_status: str | None
    expiration_year: int
    notes: list[LeaseNoteResponse]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Lease Accounting Response Schemas ---

class LeaseAccountingPeriod(BaseModel):
    period: int
    date: date
    opening_liability: Decimal
    interest: Decimal
    payment: Decimal
    principal: Decimal
    closing_liability: Decimal
    rou_carrying_value: Decimal
    lease_cost: Decimal
    lease_cost_label: str   # "Operating Lease Cost" or "Interest + Depreciation"


class LeaseMaturityAnalysis(BaseModel):
    year_1: Decimal
    year_2: Decimal
    year_3: Decimal
    year_4: Decimal
    year_5: Decimal
    thereafter: Decimal
    total_undiscounted: Decimal
    imputed_interest: Decimal
    present_value: Decimal


class LeaseJournalEntry(BaseModel):
    date: date
    account: str
    debit: Decimal | None = None
    credit: Decimal | None = None


class LeaseAccountingResponse(BaseModel):
    accounting_standard: str
    lease_classification: str
    initial_lease_liability: Decimal
    initial_rou_asset: Decimal
    currency: str
    ibr_annual: Decimal
    term_months: int
    schedule: list[LeaseAccountingPeriod]
    maturity_analysis: LeaseMaturityAnalysis
    journal_entries: list[LeaseJournalEntry]
    exempt: bool = False
    exempt_reason: str | None = None


# --- Portfolio response ---

class LeasePortfolioItem(BaseModel):
    lease_id: uuid.UUID
    lease_name: str
    office_name: str | None
    accounting_standard: str
    lease_classification: str
    initial_rou_asset: Decimal
    initial_lease_liability: Decimal
    remaining_rou: Decimal
    remaining_liability: Decimal
    ibr_annual: Decimal
    remaining_months: int
    currency: str


class LeasePortfolioResponse(BaseModel):
    leases: list[LeasePortfolioItem]
    total_rou: Decimal
    total_current_liability: Decimal
    total_noncurrent_liability: Decimal
    weighted_avg_ibr: Decimal | None
    weighted_avg_remaining_months: Decimal | None
