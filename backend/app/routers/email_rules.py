"""Email reminder rules CRUD + email log viewer."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth.dependencies import require_role
from app.models.email import EmailReminderRule, EmailLog, EmailAcknowledgement, DELIVERY_MODES
from app.utils.email_client import send_email

router = APIRouter()
# Public, token-addressed acknowledgement surface (no JWT). Mounted alongside
# the authenticated router in main.py.
public_router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────

class RuleCreate(BaseModel):
    rule_name: str
    rule_type: str
    days_before: int
    recipient_emails: list[str]
    recipient_roles: list[str] | None = None
    recipient_user_ids: list[uuid.UUID] | None = None
    delivery_mode: str = "immediate"
    escalation_offsets: list[int] | None = None
    escalation_recipient_emails: list[str] | None = None
    require_acknowledgement: bool = False
    is_active: bool = True


class RuleUpdate(BaseModel):
    rule_name: str | None = None
    rule_type: str | None = None
    days_before: int | None = None
    recipient_emails: list[str] | None = None
    recipient_roles: list[str] | None = None
    recipient_user_ids: list[uuid.UUID] | None = None
    delivery_mode: str | None = None
    escalation_offsets: list[int] | None = None
    escalation_recipient_emails: list[str] | None = None
    require_acknowledgement: bool | None = None
    is_active: bool | None = None


class RuleResponse(BaseModel):
    id: uuid.UUID
    rule_name: str
    rule_type: str
    days_before: int
    recipient_emails: list[str]
    recipient_roles: list[str] | None
    recipient_user_ids: list[uuid.UUID] | None
    delivery_mode: str
    escalation_offsets: list[int] | None
    escalation_recipient_emails: list[str] | None
    require_acknowledgement: bool
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
    escalation_level: int
    model_config = {"from_attributes": True}


class AckView(BaseModel):
    subject: str
    rule_name: str | None
    acknowledged: bool
    acknowledged_at: datetime | None
    model_config = {"from_attributes": True}


# ── Validation helpers ────────────────────────────────────────────────

VALID_RECIPIENT_ROLES = ["admin", "editor", "viewer", "accountant"]


def _validate_rule_payload(rule_type: str | None, delivery_mode: str | None, roles: list[str] | None) -> None:
    if rule_type is not None and rule_type not in VALID_RULE_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid rule_type. Must be one of: {VALID_RULE_TYPES}")
    if delivery_mode is not None and delivery_mode not in DELIVERY_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid delivery_mode. Must be one of: {list(DELIVERY_MODES)}")
    if roles:
        invalid = [r for r in roles if r not in VALID_RECIPIENT_ROLES]
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid recipient_roles {invalid}. Must be among: {VALID_RECIPIENT_ROLES}",
            )


# ── Rule Types ────────────────────────────────────────────────────────

# Canonical rule types plus their human-readable labels. The /types endpoint
# is derived from this single source so the dropdown can never drift from the
# set the API actually accepts (a missing label previously hid lease_notice).
RULE_TYPE_LABELS: dict[str, str] = {
    "lease_expiration": "Lease Expiration",
    "lease_notice_date": "Lease Notice Date",
    "lease_notice": "Lease Notice",
    "hvac_service": "HVAC Service Due",
    "hq_pm": "HQ PM Task Due",
    "high_priority_ticket": "High Priority Ticket Created",
    "ai_briefing": "AI Operations Briefing (scheduled)",
    "coi_expiration": "Insurance Certificate (COI) Expiration",
}

VALID_RULE_TYPES = list(RULE_TYPE_LABELS.keys())


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
    return [{"value": value, "label": label} for value, label in RULE_TYPE_LABELS.items()]


@router.post("/", response_model=RuleResponse, status_code=201)
async def create_rule(
    data: RuleCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role("admin")),
):
    _validate_rule_payload(data.rule_type, data.delivery_mode, data.recipient_roles)
    rule = EmailReminderRule(
        rule_name=data.rule_name,
        rule_type=data.rule_type,
        days_before=data.days_before,
        recipient_emails=data.recipient_emails,
        recipient_roles=data.recipient_roles,
        recipient_user_ids=data.recipient_user_ids,
        delivery_mode=data.delivery_mode,
        escalation_offsets=data.escalation_offsets,
        escalation_recipient_emails=data.escalation_recipient_emails,
        require_acknowledgement=data.require_acknowledgement,
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
    _validate_rule_payload(data.rule_type, data.delivery_mode, data.recipient_roles)
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
        f"<p>No action is required. This email was sent manually from Portfolio Desk.</p>"
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


# ── Public acknowledgement surface (token-addressed, unauthenticated) ─────────

async def _load_ack(db: AsyncSession, token: str) -> EmailAcknowledgement:
    result = await db.execute(
        select(EmailAcknowledgement).where(EmailAcknowledgement.ack_token == token)
    )
    ack = result.scalar_one_or_none()
    if ack is None:
        raise HTTPException(status_code=404, detail="Acknowledgement link not found")
    return ack


async def _ack_view(db: AsyncSession, ack: EmailAcknowledgement) -> AckView:
    rule = await db.get(EmailReminderRule, ack.rule_id) if ack.rule_id else None
    return AckView(
        subject=ack.subject,
        rule_name=rule.rule_name if rule else None,
        acknowledged=ack.acknowledged_at is not None,
        acknowledged_at=ack.acknowledged_at,
    )


@public_router.get("/ack/{token}", response_model=AckView)
async def view_acknowledgement(token: str, db: AsyncSession = Depends(get_db)):
    ack = await _load_ack(db, token)
    return await _ack_view(db, ack)


@public_router.post("/ack/{token}", response_model=AckView)
async def confirm_acknowledgement(token: str, db: AsyncSession = Depends(get_db)):
    ack = await _load_ack(db, token)
    if ack.acknowledged_at is None:
        ack.acknowledged_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(ack)
    return await _ack_view(db, ack)
