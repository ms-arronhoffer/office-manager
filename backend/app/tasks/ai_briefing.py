"""Scheduled AI operations briefing email.

For every active ``ai_briefing`` reminder rule this task aggregates the same
portfolio stats the ``/ai/reports/summary`` endpoint uses, asks Gemini for a
Markdown narrative, renders it to HTML (email body) plus PDF/DOCX attachments,
and emails each recipient. Every send is recorded in ``EmailLog``.

Degrades gracefully: if Gemini is not configured the narrative step raises and
the task logs and skips (no crash), mirroring the rest of the app.
"""
import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import EmailLog, EmailReminderRule
from app.services import ai_service, report_export
from app.utils.email_client import send_email, send_email_with_attachment

logger = logging.getLogger(__name__)

AI_BRIEFING_RULE_TYPE = "ai_briefing"


async def send_ai_briefings() -> None:
    """Entry point invoked by the scheduler."""
    async for db in get_db():
        await _run(db)
        break


async def _run(db: AsyncSession) -> None:
    try:
        rules = (
            await db.execute(
                select(EmailReminderRule).where(
                    EmailReminderRule.rule_type == AI_BRIEFING_RULE_TYPE,
                    EmailReminderRule.is_active == True,  # noqa: E712
                )
            )
        ).scalars().all()
    except Exception:
        logger.exception("Failed to load ai_briefing rules")
        return

    if not rules:
        logger.info("No active ai_briefing rules — skipping")
        return

    if not ai_service.is_configured():
        logger.warning("Gemini not configured — skipping ai_briefing run")
        return

    # Import here to avoid a circular import (ai router imports this module's siblings).
    from app.routers.ai import _aggregate_summary

    period_label = f"Operations Briefing — {date.today().strftime('%B %d, %Y')}"

    for rule in rules:
        try:
            data = await _aggregate_summary(db, rule.organization_id, horizon_days=30)
            narrative = await ai_service.generate_summary_narrative(period_label, data)
        except Exception:
            logger.exception("Failed to build ai_briefing for rule %s", rule.id)
            continue

        html = report_export.markdown_to_email_html(narrative, title=period_label)
        try:
            pdf_bytes = report_export.markdown_to_pdf(narrative, title=period_label)
        except Exception:
            logger.exception("Failed to render briefing PDF for rule %s", rule.id)
            pdf_bytes = None

        subject = f"AI Operations Briefing — {date.today().strftime('%B %d, %Y')}"
        for recipient in rule.recipient_emails or []:
            try:
                if pdf_bytes:
                    sent = await send_email_with_attachment(
                        recipient,
                        subject,
                        html,
                        pdf_bytes,
                        "operations-briefing.pdf",
                        "application/pdf",
                    )
                else:
                    sent = await send_email(recipient, subject, html)
                db.add(
                    EmailLog(
                        rule_id=rule.id,
                        sent_to=recipient,
                        subject=subject,
                        body=html,
                        status="sent" if sent else "failed",
                    )
                )
            except Exception:
                logger.exception("Failed to send ai_briefing to %s", recipient)

    try:
        await db.commit()
    except Exception:
        logger.exception("Failed to commit ai_briefing EmailLog rows")
        await db.rollback()

    logger.info("AI briefings sent for %s", period_label)
