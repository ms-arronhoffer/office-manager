"""Email reminder rules CRUD + email log viewer."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth.dependencies import require_role
from app.models.email import EmailReminderRule, EmailLog
from app.utils.email_client import send_email

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────

class RuleCreate(BaseModel):
    rule_name: str
    rule_type: str
    days_before: int
    recipient_emails: list[str]
    is_active: bool = True


class RuleUpdate(BaseModel):
    rule_name: str | None = None
    rule_type: str | None = None
    days_before: int | None = None
    recipient_emails: list[str] | None = None
    is_active: bool | None = None


class RuleResponse(BaseModel):
    id: uuid.UUID
    rule_name: str
    rule_type: str
    days_before: int
    recipient_emails: list[str]
    is_active: bool
    last_triggered_at: datetime | None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class EmailLogResponse(BaseModel):
    id: uuid.UUID
    rule_id: uuid.UUID | None
    sent_to: str
    subject: str
    body: str | None
    sent_at: datetime
    status: str
    model_config = {"from_attributes": True}


# ── Rule Types ────────────────────────────────────────────────────────

VALID_RULE_TYPES = ["lease_expiration", "lease_notice_date", "hvac_service", "hq_pm", "high_priority_ticket", "ai_briefing"]


# ── Endpoints ─────────────────────────────────────────────────────────

@router.get("/", response_model=list[RuleResponse])
async def list_rules(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role("admin")),
):
    stmt = select(EmailReminderRule).order_by(EmailReminderRule.rule_type, EmailReminderRule.days_before)
    result = await db.scalars(stmt)
    return result.all()


@router.get("/types")
async def list_rule_types(
    _=Depends(require_role("admin")),
):
    return [
        {"value": "lease_expiration", "label": "Lease Expiration"},
        {"value": "lease_notice_date", "label": "Lease Notice Date"},
        {"value": "hvac_service", "label": "HVAC Service Due"},
        {"value": "hq_pm", "label": "HQ PM Task Due"},
        {"value": "high_priority_ticket", "label": "High Priority Ticket Created"},
    ]


@router.post("/", response_model=RuleResponse, status_code=201)
async def create_rule(
    data: RuleCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role("admin")),
):
    if data.rule_type not in VALID_RULE_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid rule_type. Must be one of: {VALID_RULE_TYPES}")
    rule = EmailReminderRule(
        rule_name=data.rule_name,
        rule_type=data.rule_type,
        days_before=data.days_before,
        recipient_emails=data.recipient_emails,
        is_active=data.is_active,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.put("/{rule_id}", response_model=RuleResponse)
async def update_rule(
    rule_id: uuid.UUID,
    data: RuleUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role("admin")),
):
    rule = await db.get(EmailReminderRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    if data.rule_type is not None and data.rule_type not in VALID_RULE_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid rule_type. Must be one of: {VALID_RULE_TYPES}")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role("admin")),
):
    rule = await db.get(EmailReminderRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    await db.delete(rule)
    await db.commit()


@router.post("/{rule_id}/test")
async def test_rule(
    rule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role("admin")),
):
    rule = await db.get(EmailReminderRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    recipients = rule.recipient_emails or []
    if not recipients:
        return {"sent_to": [], "failed": [], "message": "Rule has no recipients configured."}

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    subject = f"[TEST] {rule.rule_name}"
    html_body = (
        f"<p>This is a test email for the email rule: <strong>{rule.rule_name}</strong>.</p>"
        f"<p>Rule type: <strong>{rule.rule_type}</strong> | Triggered at: {now_str}</p>"
        f"<p>No action is required. This email was sent manually from SwiftLease.</p>"
    )

    sent_to: list[str] = []
    failed: list[str] = []
    for recipient in recipients:
        try:
            success = await send_email(recipient, subject, html_body)
            if success:
                sent_to.append(recipient)
            else:
                failed.append(recipient)
        except Exception:
            failed.append(recipient)

    return {"sent_to": sent_to, "failed": failed}


@router.get("/logs", response_model=list[EmailLogResponse])
async def list_email_logs(
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role("admin")),
):
    stmt = select(EmailLog).order_by(EmailLog.sent_at.desc()).limit(limit)
    result = await db.scalars(stmt)
    return result.all()
