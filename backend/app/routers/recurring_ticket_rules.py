import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.auth.dependencies import get_current_user, require_role
from app.database import get_db
from app.models.office import Office as OfficeModel
from app.models.recurring_ticket_rule import RecurringTicketRule
from app.models.user import User
from app.schemas.recurring_ticket_rule import (
    RecurringTicketRuleCreate,
    RecurringTicketRuleUpdate,
    RecurringTicketRuleResponse,
)
from app.utils.tenant_scope import load_or_404

router = APIRouter()

_LOAD_OPTIONS = [
    joinedload(RecurringTicketRule.category),
    joinedload(RecurringTicketRule.office).joinedload(OfficeModel.manager),
    joinedload(RecurringTicketRule.assigned_to),
    joinedload(RecurringTicketRule.created_by),
]


def compute_next_run(frequency: str, day_of_week: int | None, day_of_month: int | None) -> datetime:
    """Compute the next run datetime (at 8am UTC) based on frequency settings."""
    now = datetime.now(timezone.utc)
    base = now.replace(hour=8, minute=0, second=0, microsecond=0)

    if frequency == "daily":
        next_run = base + timedelta(days=1)
    elif frequency == "weekly":
        if day_of_week is None:
            day_of_week = 0  # default Monday
        days_ahead = (day_of_week - now.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        next_run = base + timedelta(days=days_ahead)
    elif frequency == "monthly":
        if day_of_month is None:
            day_of_month = 1
        # Try this month first, then next month
        try:
            candidate = base.replace(day=day_of_month)
        except ValueError:
            # Day doesn't exist this month (e.g., Feb 30) — use last day
            import calendar
            last_day = calendar.monthrange(base.year, base.month)[1]
            candidate = base.replace(day=last_day)
        if candidate <= now:
            # Move to next month
            if base.month == 12:
                candidate = candidate.replace(year=base.year + 1, month=1)
            else:
                candidate = candidate.replace(month=base.month + 1)
                try:
                    candidate = candidate.replace(day=day_of_month)
                except ValueError:
                    import calendar
                    last_day = calendar.monthrange(candidate.year, candidate.month)[1]
                    candidate = candidate.replace(day=last_day)
        next_run = candidate
    else:
        next_run = base + timedelta(days=1)

    return next_run


@router.get("", response_model=list[RecurringTicketRuleResponse])
async def list_rules(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    result = await db.execute(
        select(RecurringTicketRule)
        .options(*_LOAD_OPTIONS)
        .where(RecurringTicketRule.organization_id == current_user.organization_id)
        .order_by(RecurringTicketRule.name)
    )
    return [RecurringTicketRuleResponse.model_validate(r, from_attributes=True) for r in result.scalars().unique().all()]


@router.post("", response_model=RecurringTicketRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_rule(
    payload: RecurringTicketRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    data = payload.model_dump()
    next_run = compute_next_run(data["frequency"], data.get("day_of_week"), data.get("day_of_month"))
    rule = RecurringTicketRule(
        **data,
        organization_id=current_user.organization_id,
        created_by_id=current_user.id,
        next_run_at=next_run,
    )
    db.add(rule)
    await db.commit()
    result = await db.execute(
        select(RecurringTicketRule)
        .options(*_LOAD_OPTIONS)
        .where(
            RecurringTicketRule.id == rule.id,
            RecurringTicketRule.organization_id == current_user.organization_id,
        )
    )
    return RecurringTicketRuleResponse.model_validate(result.unique().scalar_one(), from_attributes=True)


@router.put("/{rule_id}", response_model=RecurringTicketRuleResponse)
async def update_rule(
    rule_id: uuid.UUID,
    payload: RecurringTicketRuleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    rule = await load_or_404(
        db,
        RecurringTicketRule,
        rule_id,
        current_user.organization_id,
        detail="Rule not found",
    )

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(rule, field, value)

    # Recompute next_run_at if scheduling params changed
    if any(k in update_data for k in ("frequency", "day_of_week", "day_of_month")):
        rule.next_run_at = compute_next_run(rule.frequency, rule.day_of_week, rule.day_of_month)

    await db.commit()
    result = await db.execute(
        select(RecurringTicketRule)
        .options(*_LOAD_OPTIONS)
        .where(
            RecurringTicketRule.id == rule_id,
            RecurringTicketRule.organization_id == current_user.organization_id,
        )
    )
    return RecurringTicketRuleResponse.model_validate(result.unique().scalar_one(), from_attributes=True)


@router.patch("/{rule_id}/toggle", response_model=RecurringTicketRuleResponse)
async def toggle_rule(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "editor")),
):
    rule = await load_or_404(
        db,
        RecurringTicketRule,
        rule_id,
        current_user.organization_id,
        detail="Rule not found",
    )
    rule.is_active = not rule.is_active
    await db.commit()
    result = await db.execute(
        select(RecurringTicketRule)
        .options(*_LOAD_OPTIONS)
        .where(
            RecurringTicketRule.id == rule_id,
            RecurringTicketRule.organization_id == current_user.organization_id,
        )
    )
    return RecurringTicketRuleResponse.model_validate(result.unique().scalar_one(), from_attributes=True)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    rule = await load_or_404(
        db,
        RecurringTicketRule,
        rule_id,
        current_user.organization_id,
        detail="Rule not found",
    )
    await db.delete(rule)
    await db.commit()
