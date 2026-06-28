"""Tests for the email reminder-rule engine: structured recipients, escalation,
acknowledgement tracking and digest batching."""

from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.email import EmailReminderRule, EmailLog, EmailAcknowledgement
from app.models.lease import Lease
from app.models.user import User
from app.services import email_rule_engine as eng
from app.services.email_rule_engine import (
    due_escalation_level,
    resolve_recipients,
    get_or_create_acknowledgement,
)
from app.tasks.lease_reminders import check_lease_reminders
from tests.conftest import auth_headers


# ── Pure helper ────────────────────────────────────────────────────────────────

def _rule(**kw):
    defaults = dict(rule_name="r", rule_type="lease_expiration", days_before=30,
                    recipient_emails=["a@x.com"])
    defaults.update(kw)
    return EmailReminderRule(**defaults)


def test_due_escalation_level():
    rule = _rule(escalation_offsets=[3, 7])
    assert due_escalation_level(rule, 0) == 0
    assert due_escalation_level(rule, 2) == 0
    assert due_escalation_level(rule, 3) == 1
    assert due_escalation_level(rule, 6) == 1
    assert due_escalation_level(rule, 7) == 2
    assert due_escalation_level(rule, 99) == 2
    # No offsets configured -> always level 0
    assert due_escalation_level(_rule(escalation_offsets=None), 50) == 0


# ── API: rule CRUD with new fields + validation ─────────────────────────────────

@pytest.mark.asyncio
async def test_create_rule_with_new_fields(client, admin_user):
    payload = {
        "rule_name": "Lease exp", "rule_type": "lease_expiration", "days_before": 30,
        "recipient_emails": ["ops@x.com"],
        "recipient_roles": ["admin"],
        "delivery_mode": "daily_digest",
        "escalation_offsets": [3, 7],
        "escalation_recipient_emails": ["boss@x.com"],
        "require_acknowledgement": True,
    }
    r = await client.post("/api/v1/email-rules/", json=payload, headers=auth_headers(admin_user))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["delivery_mode"] == "daily_digest"
    assert body["escalation_offsets"] == [3, 7]
    assert body["require_acknowledgement"] is True
    assert body["recipient_roles"] == ["admin"]


@pytest.mark.asyncio
async def test_create_rule_rejects_bad_delivery_mode(client, admin_user):
    payload = {"rule_name": "x", "rule_type": "lease_expiration", "days_before": 10,
               "recipient_emails": ["a@x.com"], "delivery_mode": "hourly"}
    r = await client.post("/api/v1/email-rules/", json=payload, headers=auth_headers(admin_user))
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_rule_rejects_bad_role(client, admin_user):
    payload = {"rule_name": "x", "rule_type": "coi_expiration", "days_before": 10,
               "recipient_emails": ["a@x.com"], "recipient_roles": ["wizard"]}
    r = await client.post("/api/v1/email-rules/", json=payload, headers=auth_headers(admin_user))
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_coi_rule_type_allowed(client, admin_user):
    payload = {"rule_name": "coi", "rule_type": "coi_expiration", "days_before": 30,
               "recipient_emails": ["a@x.com"]}
    r = await client.post("/api/v1/email-rules/", json=payload, headers=auth_headers(admin_user))
    assert r.status_code == 201


@pytest.mark.asyncio
async def test_rule_types_endpoint_covers_all_valid_types(client, admin_user):
    """The dropdown must offer a label for every accepted rule_type, otherwise
    a valid type (e.g. lease_notice) silently fails to display."""
    from app.routers.email_rules import VALID_RULE_TYPES

    r = await client.get("/api/v1/email-rules/types", headers=auth_headers(admin_user))
    assert r.status_code == 200
    returned = {opt["value"] for opt in r.json()}
    assert returned == set(VALID_RULE_TYPES)


# ── Recipient resolution ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_recipients_expands_roles(db_session, admin_user, editor_user):
    rule = _rule(recipient_emails=["free@x.com"], recipient_roles=["admin"])
    db_session.add(rule)
    await db_session.commit()
    resolved = await resolve_recipients(db_session, rule)
    assert "free@x.com" in resolved
    assert admin_user.email in resolved
    assert editor_user.email not in resolved


@pytest.mark.asyncio
async def test_resolve_recipients_dedupes(db_session, admin_user):
    rule = _rule(recipient_emails=[admin_user.email], recipient_roles=["admin"])
    db_session.add(rule)
    await db_session.commit()
    resolved = await resolve_recipients(db_session, rule)
    assert resolved.count(admin_user.email) == 1


# ── Acknowledgement public flow ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_acknowledgement_public_flow(client, db_session):
    rule = _rule(require_acknowledgement=True)
    db_session.add(rule)
    await db_session.commit()
    ack = await get_or_create_acknowledgement(
        db_session, rule, entity_type="lease", entity_id=None, subject="Lease X expiring"
    )
    await db_session.commit()

    # View (unauthenticated)
    r = await client.get(f"/api/v1/email-rules/ack/{ack.ack_token}")
    assert r.status_code == 200
    assert r.json()["acknowledged"] is False

    # Confirm
    r = await client.post(f"/api/v1/email-rules/ack/{ack.ack_token}")
    assert r.status_code == 200
    assert r.json()["acknowledged"] is True

    # Unknown token -> 404
    assert (await client.get("/api/v1/email-rules/ack/nope")).status_code == 404


# ── End-to-end lease reminder: dedup, escalation, acknowledgement ───────────────

async def _make_lease(db, name="Lease E2E", days=10):
    lease = Lease(
        lease_name=name,
        lease_expiration=date.today() + timedelta(days=days),
        expiration_year=(date.today() + timedelta(days=days)).year,
    )
    db.add(lease)
    await db.commit()
    await db.refresh(lease)
    return lease


@pytest.mark.asyncio
async def test_lease_reminder_dedup_escalation_ack(db_session, monkeypatch):
    # Avoid real SMTP; record sends.
    sent: list[tuple[str, str]] = []

    async def _fake_send(to, subject, body):
        sent.append((to, subject))
        return True

    monkeypatch.setattr("app.tasks.lease_reminders.send_email", _fake_send)

    lease = await _make_lease(db_session)
    rule = _rule(
        rule_name="Exp", days_before=30, recipient_emails=["ops@x.com"],
        escalation_offsets=[3], escalation_recipient_emails=["boss@x.com"],
        require_acknowledgement=True,
    )
    db_session.add(rule)
    await db_session.commit()

    # Run 1: initial notice (level 0) to ops@x.com only.
    await check_lease_reminders()
    logs = (await db_session.execute(select(EmailLog))).scalars().all()
    assert len(logs) == 1
    assert logs[0].sent_to == "ops@x.com"
    assert logs[0].escalation_level == 0

    # Run 2 (same day): no new step due -> no duplicate email.
    await check_lease_reminders()
    logs = (await db_session.execute(select(EmailLog))).scalars().all()
    assert len(logs) == 1

    # Simulate the passage of time so escalation offset (3 days) elapses.
    ack = (await db_session.execute(select(EmailAcknowledgement))).scalars().one()
    ack.first_sent_at = datetime.now(timezone.utc) - timedelta(days=3)
    await db_session.commit()

    # Run 3: escalation level 1 -> ops@ + boss@.
    await check_lease_reminders()
    logs = (await db_session.execute(select(EmailLog).order_by(EmailLog.escalation_level))).scalars().all()
    esc = [l for l in logs if l.escalation_level == 1]
    assert {l.sent_to for l in esc} == {"ops@x.com", "boss@x.com"}

    # Acknowledge -> further runs send nothing more.
    ack = (await db_session.execute(select(EmailAcknowledgement))).scalars().one()
    ack.acknowledged_at = datetime.now(timezone.utc)
    ack.first_sent_at = datetime.now(timezone.utc) - timedelta(days=30)
    await db_session.commit()
    before = len((await db_session.execute(select(EmailLog))).scalars().all())
    await check_lease_reminders()
    after = len((await db_session.execute(select(EmailLog))).scalars().all())
    assert before == after


@pytest.mark.asyncio
async def test_lease_reminder_digest_batches(db_session, monkeypatch):
    combined: list[tuple[str, str, str]] = []

    async def _fake_send(to, subject, body):
        combined.append((to, subject, body))
        return True

    # Digest path flushes via the engine's DigestBuffer.send_email reference.
    monkeypatch.setattr("app.services.email_rule_engine.send_email", _fake_send)
    monkeypatch.setattr("app.tasks.lease_reminders.send_email", _fake_send)

    await _make_lease(db_session, name="Lease A", days=5)
    await _make_lease(db_session, name="Lease B", days=8)
    rule = _rule(rule_name="Digest", recipient_emails=["dig@x.com"], delivery_mode="daily_digest")
    db_session.add(rule)
    await db_session.commit()

    await check_lease_reminders()

    # One combined digest email to the single recipient covering both leases.
    digest_emails = [c for c in combined if c[1].startswith("[Digest]")]
    assert len(digest_emails) == 1
    body = digest_emails[0][2]
    assert "Lease A" in body and "Lease B" in body
