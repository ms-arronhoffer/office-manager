"""APScheduler task: render & email scheduled saved reports (Item 4A).

Queries active :class:`ReportSchedule` rows whose ``next_run_at`` has passed,
renders the linked :class:`SavedReport` via the existing report engine
(``ReportService.generate`` → the same CSV/XLSX/PDF generators used by on-demand
exports), emails the artifact to the schedule's recipients, and reschedules the
next run using the shared :func:`compute_next_run` utility.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import async_session
from app.models.saved_report import ReportSchedule, SavedReport
from app.services.report_service import DATASET_CONFIGS, ReportService
from app.utils.email_client import send_email_with_attachment
from app.utils.scheduling import compute_next_run

logger = logging.getLogger(__name__)

_CONTENT_TYPES = {
    "pdf": "application/pdf",
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


async def _render_and_send(db, schedule: ReportSchedule, report: SavedReport) -> int:
    """Render one saved report and email it to the schedule's recipients.

    Returns the number of recipients the report was successfully sent to.
    """
    service = ReportService(db)
    buffer, content_type = await service.generate(
        dataset=report.dataset,
        format=report.format,
        columns=report.columns,
        filters=report.filters,
    )
    if buffer is None:
        logger.warning(
            "Scheduled report %s references unknown dataset %r — skipping",
            report.id,
            report.dataset,
        )
        return 0

    artifact = buffer.getvalue()
    today = date.today().isoformat()
    config = DATASET_CONFIGS.get(report.dataset, {})
    title = config.get("title", report.name)
    subject = f"{report.name or title} - {today}"
    ext = report.format if report.format in _CONTENT_TYPES else "csv"
    filename = f"{report.dataset}_report_{today}.{ext}"
    html_body = (
        f"<p>Your scheduled report <strong>{report.name or title}</strong> "
        f"is attached.</p>"
    )

    sent_count = 0
    for recipient in schedule.recipients or []:
        try:
            ok = await send_email_with_attachment(
                to=recipient,
                subject=subject,
                html_body=html_body,
                attachment_bytes=artifact,
                attachment_filename=filename,
                attachment_content_type=content_type or _CONTENT_TYPES.get(ext, "text/csv"),
            )
            if ok:
                sent_count += 1
        except Exception:
            logger.exception(
                "Failed to email scheduled report %s to %s", report.id, recipient
            )
    return sent_count


async def send_scheduled_reports() -> None:
    """Render and deliver every due report schedule."""
    now = datetime.now(timezone.utc)
    logger.info("Running scheduled-report task at %s", now.isoformat())

    async with async_session() as db:
        try:
            result = await db.execute(
                select(ReportSchedule)
                .options(selectinload(ReportSchedule.saved_report))
                .where(
                    ReportSchedule.is_active.is_(True),
                    ReportSchedule.next_run_at <= now,
                )
            )
            schedules = result.scalars().all()
        except Exception:
            logger.exception("Failed to query due report schedules")
            return

        if not schedules:
            logger.info("No report schedules due — skipping")
            return

        for schedule in schedules:
            report = schedule.saved_report
            try:
                if report is not None and schedule.recipients:
                    await _render_and_send(db, schedule, report)
                schedule.last_run_at = now
                schedule.next_run_at = compute_next_run(
                    schedule.frequency, schedule.day_of_week, schedule.day_of_month, now=now
                )
            except Exception:
                logger.exception("Failed to process report schedule %s", schedule.id)

        try:
            await db.commit()
        except Exception:
            logger.exception("Failed to commit report schedule updates")
            await db.rollback()
