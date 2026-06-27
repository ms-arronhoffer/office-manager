from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Integer, Numeric, case, cast, extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models.hvac_contract import HvacContract
from app.models.lease import Lease
from app.models.maintenance_ticket import MaintenanceTicket, WorkOrderCostLine
from app.models.office import Office
from app.models.operating_expense import OperatingExpense
from app.models.transition import OfficeTransition
from app.models.user import User

router = APIRouter()


class OfficeSummary(BaseModel):
    total_offices: int
    active_offices: int
    inactive_offices: int
    active_leases: int
    upcoming_expirations_90d: int
    overdue_notices: int
    high_priority_tickets: int
    overdue_tickets: int


class LeaseExpirationGroup(BaseModel):
    year: int
    count: int


class HvacDueItem(BaseModel):
    id: str
    office_number: int | None
    office_name: str | None
    hvac_company: str | None
    next_service_date: date | None
    frequency: str | None


class ActiveTransitionItem(BaseModel):
    id: str
    office_number: int | None
    transition_type: str
    address: str | None
    status: str
    created_at: str


class UpcomingReminder(BaseModel):
    type: str
    label: str
    due_date: date | None
    days_until: int | None


@router.get("/summary", response_model=OfficeSummary)
async def get_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    today = date.today()
    cutoff_90 = today + timedelta(days=90)

    # All queries must filter by organization_id
    org_filter = Office.organization_id == current_user.organization_id

    total_result = await db.execute(select(func.count(Office.id)).where(org_filter, Office.is_deleted.is_(False)))
    total_offices = total_result.scalar_one()

    active_result = await db.execute(select(func.count(Office.id)).where(org_filter, Office.is_active == True, Office.is_deleted.is_(False)))  # noqa: E712
    active_offices = active_result.scalar_one()

    lease_count_result = await db.execute(
        select(func.count(Lease.id)).where(
            Lease.organization_id == current_user.organization_id,
            Lease.is_deleted.is_(False),
            Lease.lease_expiration.is_not(None),
            Lease.lease_expiration >= today,
        )
    )
    active_leases = lease_count_result.scalar_one()

    upcoming_result = await db.execute(
        select(func.count(Lease.id)).where(
            Lease.organization_id == current_user.organization_id,
            Lease.is_deleted.is_(False),
            Lease.lease_expiration.is_not(None),
            Lease.lease_expiration >= today,
            Lease.lease_expiration <= cutoff_90,
        )
    )
    upcoming_expirations = upcoming_result.scalar_one()

    overdue_result = await db.execute(
        select(func.count(Lease.id)).where(
            Lease.organization_id == current_user.organization_id,
            Lease.is_deleted.is_(False),
            Lease.lease_notice_date.is_not(None),
            Lease.lease_notice_date < today,
            Lease.notice_given_date.is_(None),
        )
    )
    overdue_notices = overdue_result.scalar_one()

    high_prio_result = await db.execute(
        select(func.count(MaintenanceTicket.id)).where(
            MaintenanceTicket.organization_id == current_user.organization_id,
            MaintenanceTicket.priority == "high",
            MaintenanceTicket.status != "closed",
            MaintenanceTicket.is_deleted == False,  # noqa: E712
        )
    )
    high_priority_tickets = high_prio_result.scalar_one()

    overdue_cutoff = datetime.now() - timedelta(days=7)
    overdue_result = await db.execute(
        select(func.count(MaintenanceTicket.id)).where(
            MaintenanceTicket.organization_id == current_user.organization_id,
            MaintenanceTicket.status.in_(["open", "in_progress"]),
            MaintenanceTicket.created_at < overdue_cutoff,
            MaintenanceTicket.is_deleted == False,  # noqa: E712
        )
    )
    overdue_tickets = overdue_result.scalar_one()

    return OfficeSummary(
        total_offices=total_offices,
        active_offices=active_offices,
        inactive_offices=total_offices - active_offices,
        active_leases=active_leases,
        upcoming_expirations_90d=upcoming_expirations,
        overdue_notices=overdue_notices,
        high_priority_tickets=high_priority_tickets,
        overdue_tickets=overdue_tickets,
    )


@router.get("/lease-expirations", response_model=list[LeaseExpirationGroup])
async def lease_expirations_by_year(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Lease.expiration_year, func.count(Lease.id).label("count"))
        .where(Lease.organization_id == current_user.organization_id)
        .where(Lease.is_deleted.is_(False))
        .group_by(Lease.expiration_year)
        .order_by(Lease.expiration_year)
    )
    rows = result.all()
    return [LeaseExpirationGroup(year=row.expiration_year, count=row.count) for row in rows]


@router.get("/hvac-due", response_model=list[HvacDueItem])
async def hvac_due(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cutoff = date.today() + timedelta(days=days)
    result = await db.execute(
        select(HvacContract)
        .where(HvacContract.organization_id == current_user.organization_id)
        .where(HvacContract.next_service_date.is_not(None))
        .where(HvacContract.next_service_date <= cutoff)
        .where(HvacContract.landlord_handles == False)  # noqa: E712
        .order_by(HvacContract.next_service_date)
    )
    contracts = result.scalars().all()
    return [
        HvacDueItem(
            id=str(c.id),
            office_number=c.office_number,
            office_name=c.office_name,
            hvac_company=c.hvac_company,
            next_service_date=c.next_service_date,
            frequency=c.frequency,
        )
        for c in contracts
    ]


@router.get("/active-transitions", response_model=list[ActiveTransitionItem])
async def active_transitions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(OfficeTransition)
        .where(OfficeTransition.organization_id == current_user.organization_id)
        .where(OfficeTransition.status == "in_progress")
        .order_by(OfficeTransition.created_at.desc())
    )
    transitions = result.scalars().all()
    return [
        ActiveTransitionItem(
            id=str(t.id),
            office_number=t.office_number,
            transition_type=t.transition_type,
            address=t.address,
            status=t.status,
            created_at=t.created_at.isoformat(),
        )
        for t in transitions
    ]


@router.get("/upcoming-reminders", response_model=list[UpcomingReminder])
async def upcoming_reminders(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    today = date.today()
    cutoff_30 = today + timedelta(days=30)
    cutoff_90 = today + timedelta(days=90)
    reminders: list[UpcomingReminder] = []

    # Leases expiring within 90 days
    lease_result = await db.execute(
        select(Lease)
        .where(Lease.is_deleted.is_(False))
        .where(Lease.lease_expiration.is_not(None))
        .where(Lease.lease_expiration >= today)
        .where(Lease.lease_expiration <= cutoff_90)
        .order_by(Lease.lease_expiration)
        .limit(20)
    )
    for lease in lease_result.scalars().all():
        days_until = (lease.lease_expiration - today).days if lease.lease_expiration else None
        reminders.append(
            UpcomingReminder(
                type="lease_expiration",
                label=f"Lease expiring: {lease.lease_name}",
                due_date=lease.lease_expiration,
                days_until=days_until,
            )
        )

    # Notices due within 30 days
    notice_result = await db.execute(
        select(Lease)
        .where(Lease.is_deleted.is_(False))
        .where(Lease.lease_notice_date.is_not(None))
        .where(Lease.lease_notice_date >= today)
        .where(Lease.lease_notice_date <= cutoff_30)
        .where(Lease.notice_given_date.is_(None))
        .order_by(Lease.lease_notice_date)
        .limit(20)
    )
    for lease in notice_result.scalars().all():
        days_until = (lease.lease_notice_date - today).days if lease.lease_notice_date else None
        reminders.append(
            UpcomingReminder(
                type="notice_due",
                label=f"Notice due: {lease.lease_name}",
                due_date=lease.lease_notice_date,
                days_until=days_until,
            )
        )

    # HVAC service due within 30 days
    hvac_result = await db.execute(
        select(HvacContract)
        .where(HvacContract.next_service_date.is_not(None))
        .where(HvacContract.next_service_date >= today)
        .where(HvacContract.next_service_date <= cutoff_30)
        .where(HvacContract.landlord_handles == False)  # noqa: E712
        .order_by(HvacContract.next_service_date)
        .limit(20)
    )
    for c in hvac_result.scalars().all():
        days_until = (c.next_service_date - today).days if c.next_service_date else None
        label = f"HVAC service due: {c.office_name or ('Office #' + str(c.office_number))}"
        reminders.append(
            UpcomingReminder(
                type="hvac_service",
                label=label,
                due_date=c.next_service_date,
                days_until=days_until,
            )
        )

    # Sort all reminders by days_until ascending
    reminders.sort(key=lambda r: r.days_until if r.days_until is not None else 9999)
    return reminders


# ─── Phase 2.1: Advanced Portfolio Analytics ─────────────────────────────────


class TicketVolumeMonth(BaseModel):
    year: int
    month: int
    label: str
    open: int
    closed: int
    total: int


class TopOfficeByTickets(BaseModel):
    office_id: str
    office_name: str
    office_number: int | None
    ticket_count: int


class LeaseRiskBucket(BaseModel):
    bucket: str   # "expired" | "critical" | "warning" | "healthy"
    count: int


class PortfolioHealthScore(BaseModel):
    overall: int                      # 0–100
    lease_health: int
    ticket_health: int
    hvac_health: int
    sla_compliance_pct: float
    open_high_pct: float
    lease_expiry_risk_pct: float
    hvac_overdue_pct: float


@router.get("/ticket-volume-trend", response_model=list[TicketVolumeMonth])
async def ticket_volume_trend(
    months: int = 12,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Monthly ticket open/closed counts for the last N months."""
    cutoff = datetime.now() - timedelta(days=30 * months)

    open_stmt = (
        select(
            cast(extract("year", MaintenanceTicket.created_at), Integer).label("year"),
            cast(extract("month", MaintenanceTicket.created_at), Integer).label("month"),
            func.count(MaintenanceTicket.id).label("open"),
        )
        .where(
            MaintenanceTicket.is_deleted.is_(False),
            MaintenanceTicket.organization_id == current_user.organization_id,
            MaintenanceTicket.created_at >= cutoff,
        )
        .group_by("year", "month")
    )

    closed_stmt = (
        select(
            cast(extract("year", MaintenanceTicket.closed_at), Integer).label("year"),
            cast(extract("month", MaintenanceTicket.closed_at), Integer).label("month"),
            func.count(MaintenanceTicket.id).label("closed"),
        )
        .where(
            MaintenanceTicket.is_deleted.is_(False),
            MaintenanceTicket.organization_id == current_user.organization_id,
            MaintenanceTicket.closed_at.is_not(None),
            MaintenanceTicket.closed_at >= cutoff,
        )
        .group_by("year", "month")
    )

    open_rows = {(r.year, r.month): r.open for r in (await db.execute(open_stmt)).all()}
    closed_rows = {(r.year, r.month): r.closed for r in (await db.execute(closed_stmt)).all()}

    all_keys = sorted(set(open_rows.keys()) | set(closed_rows.keys()))
    import calendar
    result = []
    for year, month in all_keys:
        o = open_rows.get((year, month), 0)
        c = closed_rows.get((year, month), 0)
        result.append(TicketVolumeMonth(
            year=year, month=month,
            label=f"{calendar.month_abbr[month]} {year}",
            open=o, closed=c, total=o,
        ))
    return result


@router.get("/top-offices-by-tickets", response_model=list[TopOfficeByTickets])
async def top_offices_by_tickets(
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(
            Office.id,
            Office.location_name,
            Office.office_number,
            func.count(MaintenanceTicket.id).label("ticket_count"),
        )
        .join(MaintenanceTicket, MaintenanceTicket.office_id == Office.id)
        .where(
            MaintenanceTicket.is_deleted.is_(False),
            MaintenanceTicket.organization_id == current_user.organization_id,
        )
        .group_by(Office.id, Office.location_name, Office.office_number)
        .order_by(func.count(MaintenanceTicket.id).desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    return [
        TopOfficeByTickets(
            office_id=str(r.id),
            office_name=r.location_name,
            office_number=r.office_number,
            ticket_count=r.ticket_count,
        )
        for r in rows
    ]


@router.get("/lease-risk", response_model=list[LeaseRiskBucket])
async def lease_risk(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Bucket leases into expired / critical (≤30d) / warning (≤90d) / healthy."""
    today = date.today()
    result = await db.execute(
        select(Lease.lease_expiration).where(
            Lease.organization_id == current_user.organization_id,
            Lease.is_deleted.is_(False),
            Lease.lease_expiration.is_not(None),
        )
    )
    expirations = [r.lease_expiration for r in result.all()]

    buckets: dict[str, int] = {"expired": 0, "critical": 0, "warning": 0, "healthy": 0}
    for exp in expirations:
        delta = (exp - today).days
        if delta < 0:
            buckets["expired"] += 1
        elif delta <= 30:
            buckets["critical"] += 1
        elif delta <= 90:
            buckets["warning"] += 1
        else:
            buckets["healthy"] += 1

    return [LeaseRiskBucket(bucket=k, count=v) for k, v in buckets.items()]


@router.get("/portfolio-health", response_model=PortfolioHealthScore)
async def portfolio_health(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Composite health score (0–100) across leases, tickets, and HVAC."""
    today = date.today()
    org_id = current_user.organization_id

    # Lease health: % of leases not expired or critical
    total_leases = (await db.execute(
        select(func.count(Lease.id)).where(
            Lease.organization_id == org_id,
            Lease.is_deleted.is_(False),
            Lease.lease_expiration.is_not(None),
        )
    )).scalar_one() or 1
    at_risk_leases = (await db.execute(
        select(func.count(Lease.id)).where(
            Lease.organization_id == org_id,
            Lease.is_deleted.is_(False),
            Lease.lease_expiration.is_not(None),
            Lease.lease_expiration <= today + timedelta(days=90),
        )
    )).scalar_one()
    lease_expiry_risk_pct = round(at_risk_leases / total_leases * 100, 1)
    lease_health = max(0, 100 - int(lease_expiry_risk_pct))

    # Ticket health: % of open tickets that are NOT high priority
    total_open = (await db.execute(
        select(func.count(MaintenanceTicket.id)).where(
            MaintenanceTicket.organization_id == org_id,
            MaintenanceTicket.is_deleted.is_(False),
            MaintenanceTicket.status != "closed",
        )
    )).scalar_one() or 1
    high_open = (await db.execute(
        select(func.count(MaintenanceTicket.id)).where(
            MaintenanceTicket.organization_id == org_id,
            MaintenanceTicket.is_deleted.is_(False),
            MaintenanceTicket.status != "closed",
            MaintenanceTicket.priority == "high",
        )
    )).scalar_one()
    open_high_pct = round(high_open / total_open * 100, 1)
    ticket_health = max(0, 100 - int(open_high_pct * 2))

    # SLA compliance: closed within 7 days for high, 14 for others
    total_closed = (await db.execute(
        select(func.count(MaintenanceTicket.id)).where(
            MaintenanceTicket.organization_id == org_id,
            MaintenanceTicket.is_deleted.is_(False),
            MaintenanceTicket.closed_at.is_not(None),
        )
    )).scalar_one() or 1
    sla_met = (await db.execute(
        select(func.count(MaintenanceTicket.id)).where(
            MaintenanceTicket.organization_id == org_id,
            MaintenanceTicket.is_deleted.is_(False),
            MaintenanceTicket.closed_at.is_not(None),
            case(
                (
                    MaintenanceTicket.priority == "high",
                    func.extract("epoch", MaintenanceTicket.closed_at - MaintenanceTicket.created_at) <= 7 * 86400,
                ),
                else_=func.extract("epoch", MaintenanceTicket.closed_at - MaintenanceTicket.created_at) <= 14 * 86400,
            ).is_(True),
        )
    )).scalar_one()
    sla_compliance_pct = round(sla_met / total_closed * 100, 1)

    # HVAC health: % of contracts with next_service_date not overdue
    total_hvac = (await db.execute(
        select(func.count(HvacContract.id)).where(
            HvacContract.next_service_date.is_not(None),
            HvacContract.landlord_handles.is_(False),
        )
    )).scalar_one() or 1
    overdue_hvac = (await db.execute(
        select(func.count(HvacContract.id)).where(
            HvacContract.next_service_date.is_not(None),
            HvacContract.landlord_handles.is_(False),
            HvacContract.next_service_date < today,
        )
    )).scalar_one()
    hvac_overdue_pct = round(overdue_hvac / total_hvac * 100, 1)
    hvac_health = max(0, 100 - int(hvac_overdue_pct))

    overall = int((lease_health * 0.35) + (ticket_health * 0.30) + (sla_compliance_pct * 0.20) + (hvac_health * 0.15))

    return PortfolioHealthScore(
        overall=overall,
        lease_health=lease_health,
        ticket_health=ticket_health,
        hvac_health=hvac_health,
        sla_compliance_pct=sla_compliance_pct,
        open_high_pct=open_high_pct,
        lease_expiry_risk_pct=lease_expiry_risk_pct,
        hvac_overdue_pct=hvac_overdue_pct,
    )


# ─── Phase 3.1: Cost-per-sqft, Maintenance Spend, Space Utilization ───────────


class CostPerSqftRow(BaseModel):
    office_id: str
    office_name: str
    office_number: int | None
    total_sqft: float | None
    annual_rent: float | None
    opex_actual: float | None
    total_annual_cost: float | None
    cost_per_sqft: float | None
    opex_by_category: dict[str, float] = {}


class MaintenanceSpendMonth(BaseModel):
    year: int
    month: int
    label: str
    labor_total: float
    materials_total: float
    grand_total: float


class SpaceUtilizationRow(BaseModel):
    office_id: str
    office_name: str
    office_number: int | None
    total_sqft: float | None
    usable_sqft: float | None
    headcount_capacity: int | None
    current_headcount: int | None
    occupancy_pct: float | None
    sqft_per_person: float | None


@router.get("/cost-per-sqft", response_model=list[CostPerSqftRow])
async def cost_per_sqft(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Per-office annual cost (rent + OpEx) divided by total_sqft."""
    org_id = current_user.organization_id

    # Annual rent per office from active leases (annualise based on payment_frequency)
    lease_rows = (await db.execute(
        select(
            Lease.office_id,
            Lease.payment_amount,
            Lease.payment_frequency,
        ).where(
            Lease.organization_id == org_id,
            Lease.is_deleted.is_(False),
            Lease.office_id.is_not(None),
            Lease.payment_amount.is_not(None),
        )
    )).all()

    freq_multiplier = {"monthly": 12, "quarterly": 4, "annually": 1}
    lease_by_office: dict[str, float] = {}
    for row in lease_rows:
        mult = freq_multiplier.get(row.payment_frequency or "monthly", 12)
        lease_by_office[str(row.office_id)] = lease_by_office.get(str(row.office_id), 0.0) + float(row.payment_amount) * mult

    # OpEx actual totals per office (via lease)
    current_year = date.today().year
    opex_rows = (await db.execute(
        select(
            Lease.office_id,
            func.sum(OperatingExpense.actual).label("opex_actual"),
        )
        .join(OperatingExpense, OperatingExpense.lease_id == Lease.id)
        .where(
            Lease.organization_id == org_id,
            Lease.is_deleted.is_(False),
            OperatingExpense.year == current_year,
            OperatingExpense.actual.is_not(None),
        )
        .group_by(Lease.office_id)
    )).all()
    opex_by_office: dict[str, float] = {str(r.office_id): float(r.opex_actual or 0) for r in opex_rows}

    # OpEx actual per office per category (for breakdown chart)
    opex_cat_rows = (await db.execute(
        select(
            Lease.office_id,
            OperatingExpense.category,
            func.sum(OperatingExpense.actual).label("cat_actual"),
        )
        .join(OperatingExpense, OperatingExpense.lease_id == Lease.id)
        .where(
            Lease.organization_id == org_id,
            Lease.is_deleted.is_(False),
            OperatingExpense.year == current_year,
            OperatingExpense.actual.is_not(None),
        )
        .group_by(Lease.office_id, OperatingExpense.category)
    )).all()
    opex_by_office_cat: dict[str, dict[str, float]] = {}
    for r in opex_cat_rows:
        oid = str(r.office_id)
        opex_by_office_cat.setdefault(oid, {})[r.category] = float(r.cat_actual or 0)

    # All offices with sqft
    offices = (await db.execute(
        select(Office).where(Office.organization_id == org_id, Office.is_active == True)  # noqa: E712
    )).scalars().all()

    result = []
    for o in offices:
        oid = str(o.id)
        annual_rent = lease_by_office.get(oid)
        opex = opex_by_office.get(oid)
        total = (annual_rent or 0) + (opex or 0) if (annual_rent or opex) else None
        sqft = float(o.total_sqft) if o.total_sqft else None
        cpp = round(total / sqft, 2) if (total and sqft) else None
        result.append(CostPerSqftRow(
            office_id=oid,
            office_name=o.location_name,
            office_number=o.office_number,
            total_sqft=sqft,
            annual_rent=annual_rent,
            opex_actual=opex,
            total_annual_cost=total,
            cost_per_sqft=cpp,
            opex_by_category=opex_by_office_cat.get(oid, {}),
        ))

    result.sort(key=lambda r: (r.cost_per_sqft is None, -(r.cost_per_sqft or 0)))
    return result


@router.get("/maintenance-spend", response_model=list[MaintenanceSpendMonth])
async def maintenance_spend(
    months: int = 12,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Monthly work-order cost totals (labor + materials) for the last N months."""
    import calendar as _cal
    cutoff = datetime.now() - timedelta(days=30 * months)
    org_id = current_user.organization_id

    stmt = (
        select(
            cast(extract("year", WorkOrderCostLine.created_at), Integer).label("year"),
            cast(extract("month", WorkOrderCostLine.created_at), Integer).label("month"),
            WorkOrderCostLine.line_type,
            func.sum(WorkOrderCostLine.quantity * WorkOrderCostLine.unit_cost).label("total"),
        )
        .join(MaintenanceTicket, MaintenanceTicket.id == WorkOrderCostLine.ticket_id)
        .where(
            MaintenanceTicket.organization_id == org_id,
            MaintenanceTicket.is_deleted.is_(False),
            WorkOrderCostLine.created_at >= cutoff,
        )
        .group_by("year", "month", WorkOrderCostLine.line_type)
    )
    rows = (await db.execute(stmt)).all()

    data: dict[tuple[int, int], dict[str, float]] = {}
    for r in rows:
        key = (r.year, r.month)
        if key not in data:
            data[key] = {"labor": 0.0, "material": 0.0}
        data[key][r.line_type] = float(r.total or 0)

    result = []
    for (year, month), totals in sorted(data.items()):
        labor = totals.get("labor", 0.0)
        mat = totals.get("material", 0.0)
        result.append(MaintenanceSpendMonth(
            year=year, month=month,
            label=f"{_cal.month_abbr[month]} {year}",
            labor_total=labor,
            materials_total=mat,
            grand_total=labor + mat,
        ))
    return result


@router.get("/space-utilization", response_model=list[SpaceUtilizationRow])
async def space_utilization(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Per-office headcount vs. capacity and sqft metrics."""
    org_id = current_user.organization_id
    offices = (await db.execute(
        select(Office).where(Office.organization_id == org_id, Office.is_active == True)  # noqa: E712
    )).scalars().all()

    result = []
    for o in offices:
        sqft = float(o.total_sqft) if o.total_sqft else None
        usable = float(o.usable_sqft) if o.usable_sqft else None
        cap = o.headcount_capacity
        cur = o.current_headcount
        occ = round(cur / cap * 100, 1) if (cap and cur is not None) else None
        spp = round(usable / cur, 1) if (usable and cur) else None
        result.append(SpaceUtilizationRow(
            office_id=str(o.id),
            office_name=o.location_name,
            office_number=o.office_number,
            total_sqft=sqft,
            usable_sqft=usable,
            headcount_capacity=cap,
            current_headcount=cur,
            occupancy_pct=occ,
            sqft_per_person=spp,
        ))

    result.sort(key=lambda r: (r.occupancy_pct is None, -(r.occupancy_pct or 0)))
    return result
