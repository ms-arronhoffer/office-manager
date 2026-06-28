"""Tests for the rule-driven COI (insurance certificate) expiration reminders
and the vendor-portal self-service re-upload surface."""

from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.email import EmailReminderRule, EmailLog, EmailAcknowledgement
from app.models.insurance_certificate import InsuranceCertificate
from app.models.vendor import Vendor
from app.tasks.insurance_reminders import check_insurance_expirations


@pytest_asyncio.fixture
async def reminder_vendor(db_session):
    vendor = Vendor(
        company_name="CoverCo",
        contact_email="cover@co.test",
        portal_token="coi-vendor-token",
        portal_token_expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db_session.add(vendor)
    await db_session.commit()
    await db_session.refresh(vendor)
    return vendor


async def _make_cert(db, vendor, *, days=10, policy="GL-1"):
    cert = InsuranceCertificate(
        vendor_id=vendor.id,
        certificate_type="general_liability",
        policy_number=policy,
        expiration_date=date.today() + timedelta(days=days),
    )
    db.add(cert)
    await db.commit()
    await db.refresh(cert)
    return cert


def _coi_rule(**kw):
    defaults = dict(
        rule_name="COI", rule_type="coi_expiration", days_before=30,
        recipient_emails=["ops@x.com"],
    )
    defaults.update(kw)
    return EmailReminderRule(**defaults)


# ── Rule-driven reminder ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_coi_reminder_sends_with_reupload_link(db_session, reminder_vendor, monkeypatch):
    sent: list[tuple[str, str, str]] = []

    async def _fake_send(to, subject, body):
        sent.append((to, subject, body))
        return True

    monkeypatch.setattr("app.tasks.insurance_reminders.send_email", _fake_send)

    await _make_cert(db_session, reminder_vendor, days=10)
    rule = _coi_rule()
    db_session.add(rule)
    await db_session.commit()

    await check_insurance_expirations()

    logs = (await db_session.execute(select(EmailLog))).scalars().all()
    assert len(logs) == 1
    assert logs[0].sent_to == "ops@x.com"
    assert logs[0].escalation_level == 0
    # Vendor-held cert deep-links to the portal re-upload page.
    assert "vendor-portal?token=" in sent[0][2]
    assert "tab=insurance" in sent[0][2]


@pytest.mark.asyncio
async def test_coi_reminder_no_rule_no_email(db_session, reminder_vendor, monkeypatch):
    sent: list = []

    async def _fake_send(to, subject, body):
        sent.append(to)
        return True

    monkeypatch.setattr("app.tasks.insurance_reminders.send_email", _fake_send)
    await _make_cert(db_session, reminder_vendor, days=5)
    # No coi_expiration rule configured -> nothing fires.
    await check_insurance_expirations()
    assert sent == []
    logs = (await db_session.execute(select(EmailLog))).scalars().all()
    assert logs == []


@pytest.mark.asyncio
async def test_coi_reminder_dedup_and_escalation(db_session, reminder_vendor, monkeypatch):
    async def _fake_send(to, subject, body):
        return True

    monkeypatch.setattr("app.tasks.insurance_reminders.send_email", _fake_send)

    await _make_cert(db_session, reminder_vendor, days=10)
    rule = _coi_rule(escalation_offsets=[3], escalation_recipient_emails=["boss@x.com"])
    db_session.add(rule)
    await db_session.commit()

    await check_insurance_expirations()
    assert len((await db_session.execute(select(EmailLog))).scalars().all()) == 1

    # Re-run same day: no new step due.
    await check_insurance_expirations()
    assert len((await db_session.execute(select(EmailLog))).scalars().all()) == 1

    # Advance time past the escalation offset.
    ack = (await db_session.execute(select(EmailAcknowledgement))).scalars().one()
    ack.first_sent_at = datetime.now(timezone.utc) - timedelta(days=3)
    await db_session.commit()

    await check_insurance_expirations()
    esc = [l for l in (await db_session.execute(select(EmailLog))).scalars().all()
           if l.escalation_level == 1]
    assert {l.sent_to for l in esc} == {"ops@x.com", "boss@x.com"}


# ── Vendor portal: read-only list + re-upload ───────────────────────────────

def _vendor_headers(token: str) -> dict[str, str]:
    return {"X-Vendor-Token": token}


@pytest.mark.asyncio
async def test_portal_list_insurance(client, db_session, reminder_vendor):
    await _make_cert(db_session, reminder_vendor, days=5, policy="GL-LIST")
    resp = await client.get(
        "/api/v1/vendor-portal/insurance", headers=_vendor_headers(reminder_vendor.portal_token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["policy_number"] == "GL-LIST"
    assert body[0]["status"] == "expiring_soon"


@pytest.mark.asyncio
async def test_portal_reupload_creates_unverified_cert(client, db_session, reminder_vendor, tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    resp = await client.post(
        "/api/v1/vendor-portal/insurance/reupload",
        headers=_vendor_headers(reminder_vendor.portal_token),
        data={
            "certificate_type": "general_liability",
            "policy_number": "NEW-123",
            "expiration_date": str(date.today() + timedelta(days=365)),
        },
        files={"file": ("coi.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["policy_number"] == "NEW-123"
    assert body["is_verified"] is False
    assert body["status"] == "active"

    # Attachment was created and scoped to the certificate.
    from app.models.attachment import Attachment
    atts = (await db_session.execute(
        select(Attachment).where(Attachment.entity_type == "insurance_certificate")
    )).scalars().all()
    assert len(atts) == 1
    assert str(atts[0].entity_id) == body["id"]


@pytest.mark.asyncio
async def test_portal_reupload_updates_existing_and_unverifies(client, db_session, reminder_vendor, tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    cert = await _make_cert(db_session, reminder_vendor, days=2, policy="OLD-1")
    cert.is_verified = True
    cert.verified_at = datetime.now(timezone.utc)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/vendor-portal/insurance/reupload",
        headers=_vendor_headers(reminder_vendor.portal_token),
        data={
            "cert_id": str(cert.id),
            "certificate_type": "general_liability",
            "expiration_date": str(date.today() + timedelta(days=400)),
        },
        files={"file": ("renew.pdf", b"%PDF-1.4 renew", "application/pdf")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"] == str(cert.id)
    assert body["is_verified"] is False


@pytest.mark.asyncio
async def test_portal_reupload_rejects_other_vendor_cert(client, db_session, reminder_vendor):
    other = Vendor(company_name="Other", portal_token="other-coi-token")
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)
    cert = await _make_cert(db_session, other, days=10, policy="OTHER-1")

    resp = await client.post(
        "/api/v1/vendor-portal/insurance/reupload",
        headers=_vendor_headers(reminder_vendor.portal_token),
        data={"cert_id": str(cert.id), "certificate_type": "general_liability"},
        files={"file": ("x.pdf", b"%PDF", "application/pdf")},
    )
    assert resp.status_code == 404
