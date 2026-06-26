"""Tests for AI briefing rendering/export (Markdown -> HTML/PDF/DOCX)."""
import io

import pytest

from app.services import ai_service, report_export

SAMPLE_MD = """# Weekly Operations Briefing

Portfolio is **stable** this week.

## Lease Deadlines
- Acme HQ notice due 2026-07-01
- Beta Suite expires 2026-08-15

## Maintenance
1. Roof leak (overdue 9 days)
2. HVAC service scheduled
"""


def test_markdown_to_html_renders_headings_and_lists():
    html = report_export.markdown_to_html(SAMPLE_MD)
    assert "<h1" in html
    assert "<ul>" in html and "<li>" in html
    assert "<ol>" in html
    assert "<strong>stable</strong>" in html


def test_markdown_to_email_html_is_full_document():
    html = report_export.markdown_to_email_html(SAMPLE_MD, title="Briefing")
    assert html.startswith("<!DOCTYPE html>")
    assert "<h1>Briefing</h1>" in html


def test_markdown_to_pdf_returns_pdf_bytes():
    pdf = report_export.markdown_to_pdf(SAMPLE_MD, title="Briefing")
    assert isinstance(pdf, bytes)
    assert pdf[:5] == b"%PDF-"


def test_markdown_to_docx_returns_readable_document():
    import docx

    data = report_export.markdown_to_docx(SAMPLE_MD, title="Briefing")
    assert isinstance(data, bytes)
    document = docx.Document(io.BytesIO(data))
    text = "\n".join(p.text for p in document.paragraphs)
    assert "Lease Deadlines" in text
    assert "Acme HQ notice due 2026-07-01" in text
    # Bold markers are stripped to plain text in DOCX.
    assert "**" not in text


# ── Endpoint ──────────────────────────────────────────────────────────────────

async def _pro_headers(db_session, email):
    from app.auth.jwt_handler import create_access_token
    from app.auth.password import hash_password
    from app.models.organization import Organization
    from app.models.user import User

    org = Organization(name="Exp Org", slug=f"exp-{email[:6]}", plan="pro")
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    user = User(
        email=email, display_name="U", password_hash=hash_password("x"),
        auth_provider="internal", role="admin", is_active=True, organization_id=org.id,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return {"Authorization": "Bearer " + token}


@pytest.mark.asyncio
async def test_export_pdf_endpoint(client, db_session):
    headers = await _pro_headers(db_session, "exppdf@test.com")
    resp = await client.post(
        "/api/v1/ai/reports/summary/export",
        headers=headers,
        json={"narrative": SAMPLE_MD, "period_label": "July 2026", "format": "pdf"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:5] == b"%PDF-"
    assert "July_2026.pdf" in resp.headers["content-disposition"]


@pytest.mark.asyncio
async def test_export_docx_endpoint(client, db_session):
    headers = await _pro_headers(db_session, "expdocx@test.com")
    resp = await client.post(
        "/api/v1/ai/reports/summary/export",
        headers=headers,
        json={"narrative": SAMPLE_MD, "period_label": "July 2026", "format": "docx"},
    )
    assert resp.status_code == 200, resp.text
    assert "wordprocessingml" in resp.headers["content-type"]
    assert "July_2026.docx" in resp.headers["content-disposition"]


@pytest.mark.asyncio
async def test_export_rejects_bad_format(client, db_session):
    headers = await _pro_headers(db_session, "expbad@test.com")
    resp = await client.post(
        "/api/v1/ai/reports/summary/export",
        headers=headers,
        json={"narrative": SAMPLE_MD, "format": "html"},
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_summary_includes_narrative_html(client, db_session, monkeypatch):
    headers = await _pro_headers(db_session, "exphtml@test.com")

    async def fake_narrative(period_label, data):
        return "# Briefing\n\n- item one"

    monkeypatch.setattr(ai_service, "generate_summary_narrative", fake_narrative)

    resp = await client.post(
        "/api/v1/ai/reports/summary", headers=headers, json={"period": "weekly"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "<h1" in body["narrative_html"]
    assert "<li>item one</li>" in body["narrative_html"]


@pytest.mark.asyncio
async def test_ai_briefing_task_sends_and_logs(db_session, monkeypatch):
    """The scheduled ai_briefing task emails recipients and records EmailLog."""
    from sqlalchemy import select

    from app.models import EmailLog, EmailReminderRule
    from app.models.organization import Organization
    from app.tasks import ai_briefing

    org = Organization(name="Brief Org", slug="brief-org", plan="pro")
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)

    rule = EmailReminderRule(
        organization_id=org.id,
        rule_name="Weekly AI briefing",
        rule_type="ai_briefing",
        days_before=0,
        recipient_emails=["ops@example.com"],
        is_active=True,
    )
    db_session.add(rule)
    await db_session.commit()

    monkeypatch.setattr(ai_briefing.ai_service, "is_configured", lambda: True)

    async def fake_narrative(period_label, data):
        return "# Briefing\n\n- All systems normal"

    monkeypatch.setattr(ai_briefing.ai_service, "generate_summary_narrative", fake_narrative)

    sent = []

    async def fake_send_with_attachment(to, subject, html, *args, **kwargs):
        sent.append(to)
        return True

    monkeypatch.setattr(ai_briefing, "send_email_with_attachment", fake_send_with_attachment)

    await ai_briefing._run(db_session)

    assert sent == ["ops@example.com"]
    logs = (
        await db_session.execute(
            select(EmailLog).where(EmailLog.sent_to == "ops@example.com")
        )
    ).scalars().all()
    assert len(logs) == 1
    assert logs[0].status == "sent"
