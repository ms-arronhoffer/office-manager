from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, cast, Integer, extract
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from app.database import get_db
from app.auth.dependencies import get_current_user
from app.models.user import User
from app.models.hq_hvac import HqHvacIssue
from app.models.maintenance_ticket import MaintenanceTicket
from app.models.site_settings import SiteSettings
from app.services.report_service import ReportService, DATASET_CONFIGS
from app.utils.email_client import send_email_with_attachment
from datetime import date

router = APIRouter()


class ReportRequest(BaseModel):
    dataset: str
    format: str = "csv"
    columns: list[str] | None = None
    filters: dict | None = None


class ReportEmailRequest(BaseModel):
    dataset: str
    columns: list[str] | None = None
    filters: dict | None = None
    recipients: list[str]
    html_body: str


_DEFAULT_SLA_DAYS = {"high": 1, "medium": 3, "low": 7}


async def _get_sla_days(db: AsyncSession) -> dict[str, int]:
    res = await db.execute(select(SiteSettings).where(SiteSettings.id == 1))
    row = res.scalar_one_or_none()
    if row is None:
        return _DEFAULT_SLA_DAYS.copy()
    return {
        "high": row.sla_high_days if row.sla_high_days is not None else _DEFAULT_SLA_DAYS["high"],
        "medium": row.sla_medium_days if row.sla_medium_days is not None else _DEFAULT_SLA_DAYS["medium"],
        "low": row.sla_low_days if row.sla_low_days is not None else _DEFAULT_SLA_DAYS["low"],
    }


@router.get("/templates")
async def get_templates(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service = ReportService(db)
    return service.get_templates()


@router.post("/preview")
async def preview_report(
    request: ReportRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service = ReportService(db)
    result = await service.preview(
        dataset=request.dataset,
        columns=request.columns,
        filters=request.filters,
    )
    if result is None:
        raise HTTPException(status_code=400, detail=f"Unknown dataset: {request.dataset}")
    return result


@router.post("/generate")
async def generate_report(
    request: ReportRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    service = ReportService(db)
    buffer, content_type = await service.generate(
        dataset=request.dataset,
        format=request.format,
        columns=request.columns,
        filters=request.filters,
    )

    if buffer is None:
        raise HTTPException(status_code=400, detail=f"Unknown dataset: {request.dataset}")

    ext_map = {"pdf": "pdf", "xlsx": "xlsx"}
    ext = ext_map.get(request.format, "csv")
    filename = f"{request.dataset}_report.{ext}"

    return StreamingResponse(
        buffer,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/email")
async def email_report(
    request: ReportEmailRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not request.recipients:
        raise HTTPException(status_code=400, detail="At least one recipient is required")

    service = ReportService(db)

    # Generate PDF
    buffer, _ = await service.generate(
        dataset=request.dataset,
        format="pdf",
        columns=request.columns,
        filters=request.filters,
    )
    if buffer is None:
        raise HTTPException(status_code=400, detail=f"Unknown dataset: {request.dataset}")

    pdf_bytes = buffer.getvalue()
    today = date.today().isoformat()
    config = DATASET_CONFIGS.get(request.dataset, {})
    title = config.get("title", request.dataset)
    subject = f"{title} - {today}"
    filename = f"{request.dataset}_report_{today}.pdf"

    results = []
    for recipient in request.recipients:
        sent = await send_email_with_attachment(
            to=recipient,
            subject=subject,
            html_body=request.html_body,
            attachment_bytes=pdf_bytes,
            attachment_filename=filename,
        )
        results.append({"recipient": recipient, "sent": sent})

    return {"results": results}


@router.get("/analytics/hvac-costs")
async def hvac_cost_analytics(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Aggregate HQ HVAC issue costs by year."""
    result = await db.execute(
        select(
            extract("year", HqHvacIssue.issue_date).label("year"),
            func.sum(HqHvacIssue.cost).label("total_cost"),
            func.count(HqHvacIssue.id).label("issue_count"),
        )
        .where(HqHvacIssue.issue_date != None)  # noqa: E711
        .group_by(extract("year", HqHvacIssue.issue_date))
        .order_by(extract("year", HqHvacIssue.issue_date))
    )
    rows = result.all()
    return [
        {
            "year": int(row.year),
            "total_cost": float(row.total_cost or 0),
            "issue_count": int(row.issue_count),
        }
        for row in rows
    ]


@router.get("/analytics/ticket-resolution")
async def ticket_resolution_analytics(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Average days to close tickets by priority and category."""
    from sqlalchemy.orm import joinedload
    from app.models.maintenance_ticket import MaintenanceTicket

    result = await db.execute(
        select(MaintenanceTicket).where(
            MaintenanceTicket.status == "closed",
            MaintenanceTicket.is_deleted.is_(False),
            MaintenanceTicket.created_at != None,  # noqa: E711
            MaintenanceTicket.updated_at != None,  # noqa: E711
        ).options(joinedload(MaintenanceTicket.category))
    )
    tickets = result.scalars().unique().all()

    by_priority: dict[str, list[float]] = {}
    by_category: dict[str, list[float]] = {}

    for t in tickets:
        if t.created_at and t.updated_at:
            days = (t.updated_at - t.created_at).total_seconds() / 86400
            if days < 0:
                continue
            by_priority.setdefault(t.priority, []).append(days)
            cat = t.category.name if t.category else "Uncategorized"
            by_category.setdefault(cat, []).append(days)

    def avg(lst: list[float]) -> float:
        return round(sum(lst) / len(lst), 1) if lst else 0.0

    return {
        "by_priority": [
            {"label": k, "avg_days": avg(v), "count": len(v)}
            for k, v in sorted(by_priority.items())
        ],
        "by_category": [
            {"label": k, "avg_days": avg(v), "count": len(v)}
            for k, v in sorted(by_category.items(), key=lambda x: -avg(x[1]))
        ],
    }


@router.get("/analytics/sla")
async def sla_analytics(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """SLA breach rates for open/in_progress tickets by priority and office."""
    from datetime import datetime, timezone
    from sqlalchemy.orm import joinedload

    SLA_DAYS = await _get_sla_days(db)

    result = await db.execute(
        select(MaintenanceTicket)
        .options(joinedload(MaintenanceTicket.office))
        .where(
            MaintenanceTicket.is_deleted.is_(False),
            MaintenanceTicket.status.in_(["open", "in_progress"]),
            MaintenanceTicket.created_at != None,  # noqa: E711
        )
    )
    tickets = result.scalars().unique().all()

    now = datetime.now(timezone.utc)

    # Aggregate by priority
    by_priority: dict[str, dict] = {}
    # Aggregate by office+priority
    by_office_priority: dict[tuple, dict] = {}

    for t in tickets:
        if not t.created_at:
            continue

        created = t.created_at
        if created.tzinfo is None:
            from datetime import timezone as tz
            created = created.replace(tzinfo=tz.utc)

        days_open = (now - created).days
        threshold = SLA_DAYS.get(t.priority, 7)
        breached = days_open > threshold

        office_name = t.office.location_name if t.office else "Unknown"

        # by priority
        p = by_priority.setdefault(t.priority, {"total": 0, "breached": 0, "days_sum": 0})
        p["total"] += 1
        p["days_sum"] += days_open
        if breached:
            p["breached"] += 1

        # by office+priority
        key = (office_name, t.priority)
        op = by_office_priority.setdefault(key, {"total": 0, "breached": 0, "days_sum": 0})
        op["total"] += 1
        op["days_sum"] += days_open
        if breached:
            op["breached"] += 1

    open_summary = [
        {
            "priority": priority,
            "total": d["total"],
            "breached": d["breached"],
            "breach_rate": round(d["breached"] / d["total"], 3) if d["total"] else 0,
            "avg_days_open": round(d["days_sum"] / d["total"], 1) if d["total"] else 0,
        }
        for priority, d in sorted(by_priority.items())
    ]

    by_office = [
        {
            "office": office,
            "priority": priority,
            "total": d["total"],
            "breached": d["breached"],
            "breach_rate": round(d["breached"] / d["total"], 3) if d["total"] else 0,
            "avg_days_open": round(d["days_sum"] / d["total"], 1) if d["total"] else 0,
        }
        for (office, priority), d in sorted(by_office_priority.items())
    ]

    # Average resolution time for closed tickets (using closed_at)
    closed_result = await db.execute(
        select(MaintenanceTicket)
        .where(
            MaintenanceTicket.is_deleted.is_(False),
            MaintenanceTicket.status == "closed",
            MaintenanceTicket.closed_at.is_not(None),
            MaintenanceTicket.created_at.is_not(None),
        )
    )
    closed_tickets = closed_result.scalars().all()

    resolution_by_priority: dict[str, dict] = {}
    for t in closed_tickets:
        closed = t.closed_at
        created = t.created_at
        if closed.tzinfo is None:
            closed = closed.replace(tzinfo=timezone.utc)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        resolution_days = (closed - created).total_seconds() / 86400
        r = resolution_by_priority.setdefault(t.priority, {"count": 0, "total_days": 0.0})
        r["count"] += 1
        r["total_days"] += resolution_days

    resolution_summary = [
        {
            "priority": priority,
            "resolved_count": d["count"],
            "avg_resolution_days": round(d["total_days"] / d["count"], 1) if d["count"] else 0,
        }
        for priority, d in sorted(resolution_by_priority.items())
    ]

    return {
        "open_summary": open_summary,
        "by_office": by_office,
        "sla_thresholds": SLA_DAYS,
        "resolution_summary": resolution_summary,
    }


@router.get("/lease-accounting-portfolio")
async def lease_accounting_portfolio(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Portfolio-level ASC 842 / IFRS 16 summary for all leases with accounting data.
    Returns per-lease ROU / liability values (remaining as of today) plus portfolio totals.
    """
    from datetime import date as _date
    from decimal import Decimal
    from sqlalchemy.orm import joinedload
    from app.models.lease import Lease
    from app.services.lease_accounting import compute_portfolio_row

    result = await db.execute(
        select(Lease)
        .options(joinedload(Lease.office))
        .where(
            Lease.is_deleted.is_(False),
            Lease.accounting_standard.is_not(None),
        )
    )
    leases = result.scalars().unique().all()

    today = _date.today()
    rows = []
    for lease in leases:
        row = compute_portfolio_row(lease, today)
        if row:
            rows.append(row)

    total_rou = sum(float(r["remaining_rou"]) for r in rows)
    total_current = sum(float(r["current_liability"]) for r in rows)
    total_noncurrent = sum(float(r["noncurrent_liability"]) for r in rows)

    # Weighted average IBR (weight = remaining_liability)
    total_weight = sum(float(r["remaining_liability"]) for r in rows)
    if total_weight > 0:
        wtd_ibr = sum(float(r["ibr_annual"]) * float(r["remaining_liability"]) for r in rows) / total_weight
        wtd_months = sum(float(r["remaining_months"]) * float(r["remaining_liability"]) for r in rows) / total_weight
    else:
        wtd_ibr = None
        wtd_months = None

    return {
        "leases": [
            {
                "lease_id": str(r["lease_id"]),
                "lease_name": r["lease_name"],
                "office_name": r["office_name"],
                "accounting_standard": r["accounting_standard"],
                "lease_classification": r["lease_classification"],
                "initial_rou_asset": float(r["initial_rou_asset"]),
                "initial_lease_liability": float(r["initial_lease_liability"]),
                "remaining_rou": float(r["remaining_rou"]),
                "remaining_liability": float(r["remaining_liability"]),
                "ibr_annual": float(r["ibr_annual"]),
                "remaining_months": r["remaining_months"],
                "currency": r["currency"],
            }
            for r in rows
        ],
        "total_rou": round(total_rou, 2),
        "total_current_liability": round(total_current, 2),
        "total_noncurrent_liability": round(total_noncurrent, 2),
        "weighted_avg_ibr": round(wtd_ibr, 6) if wtd_ibr is not None else None,
        "weighted_avg_remaining_months": round(wtd_months, 1) if wtd_months is not None else None,
    }


@router.get("/accounting/amortization/{lease_id}")
async def export_amortization_schedule(
    lease_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Export the full ASC 842 / IFRS 16 amortization schedule for a single lease as CSV.
    """
    import io
    import csv
    import uuid as _uuid
    from sqlalchemy.orm import joinedload
    from app.models.lease import Lease
    from app.services.lease_accounting import compute_lease_accounting

    try:
        lease_uuid = _uuid.UUID(lease_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid lease ID")

    result = await db.execute(
        select(Lease)
        .options(joinedload(Lease.office))
        .where(Lease.id == lease_uuid, Lease.is_deleted.is_(False))
    )
    lease = result.scalar_one_or_none()
    if lease is None:
        raise HTTPException(status_code=404, detail="Lease not found")

    try:
        data = compute_lease_accounting(lease, include_journal_entries=False)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    if data.get("exempt"):
        raise HTTPException(status_code=422, detail=data.get("exempt_reason", "Lease is exempt from recognition."))

    schedule = data["schedule"]
    currency = data["currency"]
    standard = data["accounting_standard"].upper()
    classification = data["lease_classification"].capitalize()

    buf = io.StringIO()
    writer = csv.writer(buf)

    # Header block
    writer.writerow([f"Amortization Schedule — {lease.lease_name}"])
    writer.writerow([f"Standard: {standard} | Classification: {classification} | Currency: {currency}"])
    writer.writerow([f"Initial Lease Liability: {float(data['initial_lease_liability']):.2f} | Initial ROU Asset: {float(data['initial_rou_asset']):.2f} | IBR: {float(data['ibr_annual']) * 100:.4f}% annual | Term: {data['term_months']} months"])
    writer.writerow([])

    # Column headers
    writer.writerow([
        "Period",
        "Date",
        "Opening Liability",
        "Interest",
        "Payment",
        "Principal",
        "Closing Liability",
        "ROU Carrying Value",
        "Lease Cost",
    ])

    for row in schedule:
        writer.writerow([
            row["period"],
            row["date"].isoformat(),
            f"{float(row['opening_liability']):.2f}",
            f"{float(row['interest']):.2f}",
            f"{float(row['payment']):.2f}",
            f"{float(row['principal']):.2f}",
            f"{float(row['closing_liability']):.2f}",
            f"{float(row['rou_carrying_value']):.2f}",
            f"{float(row['lease_cost']):.2f}",
        ])

    buf.seek(0)
    safe_name = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in lease.lease_name)
    filename = f"amortization_{safe_name}.csv"

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/accounting/maturity")
async def export_maturity_analysis(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Export the portfolio-wide maturity analysis disclosure as CSV (ASC 842 / IFRS 16 Note).
    Sums Year 1–5 + Thereafter buckets across all leases that have accounting data.
    """
    import io
    import csv
    from sqlalchemy.orm import joinedload
    from app.models.lease import Lease
    from app.services.lease_accounting import compute_lease_accounting
    from decimal import Decimal

    result = await db.execute(
        select(Lease)
        .options(joinedload(Lease.office))
        .where(
            Lease.is_deleted.is_(False),
            Lease.accounting_standard.is_not(None),
        )
    )
    leases = result.scalars().unique().all()

    rows = []
    bucket_keys = ["year_1", "year_2", "year_3", "year_4", "year_5", "thereafter"]

    for lease in leases:
        try:
            data = compute_lease_accounting(lease, include_journal_entries=False)
        except Exception:
            continue
        if data.get("exempt"):
            continue
        mat = data["maturity_analysis"]
        rows.append({
            "lease_name": lease.lease_name,
            "office": lease.office.location_name if lease.office else "",
            "standard": data["accounting_standard"].upper(),
            "classification": data["lease_classification"].capitalize(),
            "currency": data["currency"],
            **{k: float(mat[k]) for k in bucket_keys},
            "total_undiscounted": float(mat["total_undiscounted"]),
            "imputed_interest": float(mat["imputed_interest"]),
            "present_value": float(mat["present_value"]),
        })

    # Portfolio totals (USD-equivalent; currencies mixed but labelled per row)
    def _sum(field: str) -> float:
        return sum(r[field] for r in rows)

    buf = io.StringIO()
    writer = csv.writer(buf)

    writer.writerow(["Maturity Analysis — Portfolio Lease Obligations"])
    writer.writerow([f"Leases included: {len(rows)} | Generated: {date.today().isoformat()}"])
    writer.writerow([])

    writer.writerow([
        "Lease Name", "Office", "Standard", "Classification", "Currency",
        "Year 1", "Year 2", "Year 3", "Year 4", "Year 5", "Thereafter",
        "Total Undiscounted", "Imputed Interest", "Present Value (Liability)",
    ])

    for r in rows:
        writer.writerow([
            r["lease_name"],
            r["office"],
            r["standard"],
            r["classification"],
            r["currency"],
            f"{r['year_1']:.2f}",
            f"{r['year_2']:.2f}",
            f"{r['year_3']:.2f}",
            f"{r['year_4']:.2f}",
            f"{r['year_5']:.2f}",
            f"{r['thereafter']:.2f}",
            f"{r['total_undiscounted']:.2f}",
            f"{r['imputed_interest']:.2f}",
            f"{r['present_value']:.2f}",
        ])

    # Totals row
    writer.writerow([
        "PORTFOLIO TOTAL", "", "", "", "(mixed)",
        f"{_sum('year_1'):.2f}",
        f"{_sum('year_2'):.2f}",
        f"{_sum('year_3'):.2f}",
        f"{_sum('year_4'):.2f}",
        f"{_sum('year_5'):.2f}",
        f"{_sum('thereafter'):.2f}",
        f"{_sum('total_undiscounted'):.2f}",
        f"{_sum('imputed_interest'):.2f}",
        f"{_sum('present_value'):.2f}",
    ])

    buf.seek(0)
    filename = f"maturity_analysis_{date.today().isoformat()}.csv"

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
