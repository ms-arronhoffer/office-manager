from datetime import date, timedelta
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from app.models import (
    Office, Lease, HvacContract, HqPmTask, OfficeTransition, EmailReminderRule
)


class DashboardService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_summary(self) -> dict:
        today = date.today()
        upcoming_90 = today + timedelta(days=90)

        active_offices = await self.db.execute(
            select(func.count(Office.id)).where(Office.is_active == True)
        )
        inactive_offices = await self.db.execute(
            select(func.count(Office.id)).where(Office.is_active == False)
        )
        total_leases = await self.db.execute(select(func.count(Lease.id)))
        upcoming_expirations = await self.db.execute(
            select(func.count(Lease.id)).where(
                Lease.lease_expiration != None,
                Lease.lease_expiration <= upcoming_90,
                Lease.lease_expiration >= today,
            )
        )
        overdue_notices = await self.db.execute(
            select(func.count(Lease.id)).where(
                Lease.lease_notice_date != None,
                Lease.lease_notice_date < today,
                Lease.notice_given_date == None,
            )
        )
        active_transitions = await self.db.execute(
            select(func.count(OfficeTransition.id)).where(
                OfficeTransition.status == "in_progress"
            )
        )

        return {
            "active_offices": active_offices.scalar() or 0,
            "inactive_offices": inactive_offices.scalar() or 0,
            "total_leases": total_leases.scalar() or 0,
            "upcoming_expirations_90d": upcoming_expirations.scalar() or 0,
            "overdue_notices": overdue_notices.scalar() or 0,
            "active_transitions": active_transitions.scalar() or 0,
        }

    async def get_lease_expirations_by_year(self) -> list[dict]:
        result = await self.db.execute(
            select(Lease.expiration_year, func.count(Lease.id))
            .group_by(Lease.expiration_year)
            .order_by(Lease.expiration_year)
        )
        return [{"year": row[0], "count": row[1]} for row in result.all()]

    async def get_hvac_due(self, days: int = 30) -> list[dict]:
        cutoff = date.today() + timedelta(days=days)
        result = await self.db.execute(
            select(HvacContract).options(joinedload(HvacContract.manager)).where(
                HvacContract.next_service_date != None,
                HvacContract.next_service_date <= cutoff,
                HvacContract.next_service_date >= date.today(),
            ).order_by(HvacContract.next_service_date)
        )
        contracts = result.unique().scalars().all()
        return [
            {
                "id": str(c.id),
                "office_name": c.office_name,
                "hvac_company": c.hvac_company,
                "next_service_date": str(c.next_service_date),
                "manager": c.manager.name if c.manager else None,
            }
            for c in contracts
        ]

    async def get_active_transitions(self) -> list[dict]:
        result = await self.db.execute(
            select(OfficeTransition).where(OfficeTransition.status == "in_progress")
        )
        transitions = result.scalars().all()
        return [
            {
                "id": str(t.id),
                "office_number": t.office_number,
                "transition_type": t.transition_type,
                "address": t.address,
                "sheet_name": t.sheet_name,
            }
            for t in transitions
        ]
