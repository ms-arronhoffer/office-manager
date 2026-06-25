"""
ASC 842 / IFRS 16 lease accounting computation engine.

Computes on-the-fly (no DB storage) for a single lease:
  - Initial Lease Liability  (PV of future payments discounted at IBR)
  - Initial ROU Asset
  - Month-by-month amortization schedule
  - Maturity analysis (undiscounted payments by year bucket)
  - Journal entries

Supports:
  - ASC 842 Operating and Finance classifications
  - IFRS 16 (always finance-like treatment)
  - Fixed % annual escalation
  - Monthly, quarterly, and annual payment frequencies
  - Short-term / low-value exemptions (returns exempt flag)
"""

import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TWO = Decimal("0.01")      # quantize target for currency amounts
SIX = Decimal("0.000001")  # quantize target for rates


def _q(value: Decimal | float | int) -> Decimal:
    """Round to 2 decimal places (currency)."""
    return Decimal(str(value)).quantize(TWO, rounding=ROUND_HALF_UP)


def _add_months(d: date, months: int) -> date:
    """Add `months` to a date, clamping the day if the target month is shorter."""
    total_months = d.month - 1 + months
    year = d.year + total_months // 12
    month = total_months % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _months_between(start: date, end: date) -> int:
    """Number of full calendar months from start to end (end exclusive)."""
    return (end.year - start.year) * 12 + (end.month - start.month)


def _compound_monthly_rate(annual_rate: Decimal) -> Decimal:
    """Convert annual effective rate to compound monthly rate."""
    r = float(annual_rate)
    monthly = (1 + r) ** (1 / 12) - 1
    return Decimal(str(monthly))


def _is_payment_month(t: int, frequency: str) -> bool:
    """Return True if period t (1-indexed) is a payment period."""
    if frequency == "monthly":
        return True
    if frequency == "quarterly":
        return t % 3 == 0
    if frequency == "annually":
        return t % 12 == 0
    return True  # fallback


def _payment_for_period(t: int, payment_amount: Decimal, annual_escalation: Decimal, frequency: str) -> Decimal:
    """Return the cash payment due in period t (0 for non-payment months)."""
    if not _is_payment_month(t, frequency):
        return Decimal("0")
    year_index = (t - 1) // 12  # 0-indexed full years elapsed
    factor = (1 + float(annual_escalation)) ** year_index
    return _q(payment_amount * Decimal(str(factor)))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def compute_lease_accounting(
    lease,
    include_journal_entries: bool = False,
) -> dict:
    """
    Compute full ASC 842 / IFRS 16 accounting for a Lease ORM instance.

    Returns a dict matching LeaseAccountingResponse schema.
    Raises ValueError with a human-readable message if required fields are missing.
    """
    # --- Exemption check ---
    if getattr(lease, "is_short_term_lease", False):
        return {"exempt": True, "exempt_reason": "Short-term lease (<12 months) — exempt from ROU/Liability recognition."}
    if getattr(lease, "is_low_value_lease", False):
        return {"exempt": True, "exempt_reason": "Low-value lease (IFRS 16) — exempt from recognition."}

    # --- Required field validation ---
    missing = []
    if not lease.lease_commencement_date:
        missing.append("lease_commencement_date")
    if not lease.lease_expiration:
        missing.append("lease_expiration")
    if lease.payment_amount is None:
        missing.append("payment_amount")
    if lease.incremental_borrowing_rate is None:
        missing.append("incremental_borrowing_rate")
    if missing:
        raise ValueError(f"Cannot compute accounting schedule — missing fields: {', '.join(missing)}")

    commencement: date = lease.lease_commencement_date
    expiration: date = lease.lease_expiration
    n = _months_between(commencement, expiration)
    if n <= 0:
        raise ValueError("Lease expiration must be after commencement date.")

    payment_amount = Decimal(str(lease.payment_amount))
    ibr = Decimal(str(lease.incremental_borrowing_rate))
    escalation = Decimal(str(lease.annual_escalation_rate or 0))
    frequency = lease.payment_frequency or "monthly"
    accounting_standard = lease.accounting_standard or "asc842"
    currency = lease.currency or "USD"

    # Determine effective classification
    # IFRS 16 = always finance-like. ASC 842 = use lease_classification field.
    if accounting_standard == "ifrs16":
        classification = "finance"
    else:
        classification = lease.lease_classification or "operating"

    initial_direct_costs = _q(lease.initial_direct_costs or 0)
    lease_incentives = _q(lease.lease_incentives or 0)
    prepaid_rent = _q(lease.prepaid_rent or 0)
    residual_value_guarantee = _q(lease.residual_value_guarantee or 0)

    monthly_rate = _compound_monthly_rate(ibr)

    # --- Step 1: Build payment array ---
    payments = [_payment_for_period(t, payment_amount, escalation, frequency) for t in range(1, n + 1)]

    # --- Step 2: Initial Lease Liability (PV) ---
    initial_liability = Decimal("0")
    for t, pmt in enumerate(payments, start=1):
        if pmt > 0:
            denominator = (1 + float(monthly_rate)) ** t
            initial_liability += _q(pmt / Decimal(str(denominator)))
    # Add PV of residual value guarantee at end of term
    if residual_value_guarantee > 0:
        denominator = (1 + float(monthly_rate)) ** n
        initial_liability += _q(residual_value_guarantee / Decimal(str(denominator)))
    initial_liability = _q(initial_liability)

    # --- Step 3: Initial ROU Asset ---
    initial_rou = _q(initial_liability + initial_direct_costs + prepaid_rent - lease_incentives + residual_value_guarantee)

    # --- Step 4: Pre-compute operating straight-line cost ---
    total_undiscounted = _q(sum(payments))
    if classification == "operating":
        total_cost = _q(total_undiscounted + initial_direct_costs + prepaid_rent - lease_incentives)
        straight_line_cost = _q(total_cost / n)
        lease_cost_label = "Operating Lease Cost"
    else:
        rou_depr_per_period = _q(initial_rou / n)
        lease_cost_label = "Interest + Depreciation"

    # --- Step 5: Build amortization schedule ---
    schedule = []
    opening_liability = initial_liability
    cumulative_rou_amort = Decimal("0")

    for t in range(1, n + 1):
        pmt = payments[t - 1]
        period_date = _add_months(commencement, t)

        interest = _q(opening_liability * monthly_rate)
        principal = _q(pmt - interest)
        closing_liability = _q(opening_liability - principal)

        # Force to zero on final period to absorb rounding
        if t == n:
            closing_liability = Decimal("0")

        if classification == "finance":
            rou_charge = rou_depr_per_period
            rou_carrying = _q(initial_rou - t * rou_depr_per_period)
            lease_cost = _q(interest + rou_charge)
        else:  # operating
            rou_amort = _q(straight_line_cost - interest)
            cumulative_rou_amort = _q(cumulative_rou_amort + rou_amort)
            rou_carrying = _q(initial_rou - cumulative_rou_amort)
            lease_cost = straight_line_cost

        schedule.append({
            "period": t,
            "date": period_date,
            "opening_liability": opening_liability,
            "interest": interest,
            "payment": pmt,
            "principal": principal,
            "closing_liability": closing_liability,
            "rou_carrying_value": rou_carrying,
            "lease_cost": lease_cost,
            "lease_cost_label": lease_cost_label,
        })

        opening_liability = closing_liability

    # --- Step 6: Maturity analysis ---
    buckets = {"year_1": 0, "year_2": 0, "year_3": 0, "year_4": 0, "year_5": 0, "thereafter": 0}
    for t, pmt in enumerate(payments, start=1):
        if t <= 12:
            buckets["year_1"] += float(pmt)
        elif t <= 24:
            buckets["year_2"] += float(pmt)
        elif t <= 36:
            buckets["year_3"] += float(pmt)
        elif t <= 48:
            buckets["year_4"] += float(pmt)
        elif t <= 60:
            buckets["year_5"] += float(pmt)
        else:
            buckets["thereafter"] += float(pmt)
    # Add residual value guarantee to final period bucket
    if residual_value_guarantee > 0:
        bucket_key = "thereafter" if n > 60 else (
            "year_5" if n > 48 else (
                "year_4" if n > 36 else (
                    "year_3" if n > 24 else (
                        "year_2" if n > 12 else "year_1"
                    )
                )
            )
        )
        buckets[bucket_key] += float(residual_value_guarantee)

    mat = {k: _q(v) for k, v in buckets.items()}
    total_undi = _q(sum(mat.values()))
    imputed = _q(float(total_undi) - float(initial_liability))
    maturity_analysis = {
        **mat,
        "total_undiscounted": total_undi,
        "imputed_interest": imputed,
        "present_value": initial_liability,
    }

    # --- Step 7: Journal entries (optional) ---
    journal_entries = []
    if include_journal_entries:
        # Commencement entry
        journal_entries.append({"date": commencement, "account": "Right-of-Use Asset", "debit": initial_rou, "credit": None})
        journal_entries.append({"date": commencement, "account": "Lease Liability", "debit": None, "credit": initial_liability})
        if initial_direct_costs > 0 or prepaid_rent > 0 or lease_incentives > 0:
            journal_entries.append({"date": commencement, "account": "— (included in ROU above)", "debit": None, "credit": None})

        for row in schedule:
            pmt = row["payment"]
            interest = row["interest"]
            principal = row["principal"]
            period_date = row["date"]

            if classification == "finance":
                rou_depr = rou_depr_per_period
                journal_entries.append({"date": period_date, "account": "Interest Expense", "debit": interest, "credit": None})
                journal_entries.append({"date": period_date, "account": "Depreciation Expense", "debit": rou_depr, "credit": None})
                if principal > 0:
                    journal_entries.append({"date": period_date, "account": "Lease Liability", "debit": principal, "credit": None})
                else:
                    # Non-payment month: liability accrues (credit)
                    journal_entries.append({"date": period_date, "account": "Lease Liability", "debit": None, "credit": _q(-principal)})
                journal_entries.append({"date": period_date, "account": "Accumulated Depreciation", "debit": None, "credit": rou_depr})
                if pmt > 0:
                    journal_entries.append({"date": period_date, "account": "Cash", "debit": None, "credit": pmt})
            else:
                # Operating
                sl_cost = straight_line_cost
                rou_amort = _q(sl_cost - interest)
                journal_entries.append({"date": period_date, "account": "Operating Lease Cost", "debit": sl_cost, "credit": None})
                if principal > 0:
                    journal_entries.append({"date": period_date, "account": "Lease Liability", "debit": principal, "credit": None})
                else:
                    journal_entries.append({"date": period_date, "account": "Lease Liability", "debit": None, "credit": _q(-principal)})
                if rou_amort >= 0:
                    journal_entries.append({"date": period_date, "account": "Right-of-Use Asset", "debit": None, "credit": rou_amort})
                else:
                    journal_entries.append({"date": period_date, "account": "Right-of-Use Asset", "debit": _q(-rou_amort), "credit": None})
                if pmt > 0:
                    journal_entries.append({"date": period_date, "account": "Cash", "debit": None, "credit": pmt})

    return {
        "accounting_standard": accounting_standard,
        "lease_classification": classification,
        "initial_lease_liability": initial_liability,
        "initial_rou_asset": initial_rou,
        "currency": currency,
        "ibr_annual": ibr,
        "term_months": n,
        "schedule": schedule,
        "maturity_analysis": maturity_analysis,
        "journal_entries": journal_entries,
        "exempt": False,
        "exempt_reason": None,
    }


def compute_portfolio_row(lease, today: date | None = None) -> dict | None:
    """
    Compute a single portfolio row for a lease.
    Returns None if computation fails (missing fields, expired, etc.).
    """
    if today is None:
        from datetime import date as _date
        today = _date.today()

    try:
        full = compute_lease_accounting(lease, include_journal_entries=False)
    except (ValueError, Exception):
        return None

    if full.get("exempt"):
        return None

    schedule = full["schedule"]
    if not schedule:
        return None

    # Find where we are today in the schedule
    commencement: date = lease.lease_commencement_date
    months_elapsed = _months_between(commencement, today)
    months_elapsed = max(0, min(months_elapsed, len(schedule)))

    # Remaining schedule rows
    remaining = schedule[months_elapsed:]
    remaining_liability = remaining[0]["opening_liability"] if remaining else Decimal("0")
    remaining_rou = remaining[0]["rou_carrying_value"] if remaining else Decimal("0")
    remaining_months = len(remaining)

    # Current vs non-current: current = payments in next 12 months from today
    current_months = remaining[:12]
    current_liability = _q(sum(float(r["principal"]) for r in current_months if float(r["principal"]) > 0))
    noncurrent_liability = _q(float(remaining_liability) - float(current_liability))

    return {
        "lease_id": lease.id,
        "lease_name": lease.lease_name,
        "office_name": lease.office.location_name if lease.office else None,
        "accounting_standard": full["accounting_standard"],
        "lease_classification": full["lease_classification"],
        "initial_rou_asset": full["initial_rou_asset"],
        "initial_lease_liability": full["initial_lease_liability"],
        "remaining_rou": remaining_rou,
        "remaining_liability": remaining_liability,
        "current_liability": current_liability,
        "noncurrent_liability": noncurrent_liability,
        "ibr_annual": full["ibr_annual"],
        "remaining_months": remaining_months,
        "currency": full["currency"],
    }
