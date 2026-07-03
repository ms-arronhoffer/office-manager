"""Tenant-screening client (Phase 2.4).

A thin, provider-agnostic wrapper around a third-party tenant-screening service
(credit / criminal / eviction checks). Like the SMS and payment clients, it
degrades gracefully when unconfigured: without ``SCREENING_API_KEY`` it returns a
``manual`` report flagged for staff review rather than calling out, so the leasing
funnel keeps working in dev/test without a live vendor.

No PII beyond what the caller passes is stored here; the returned ``report_data``
is a summary dict the caller persists on a :class:`~app.models.leasing_funnel.ScreeningReport`.
"""

import logging
from dataclasses import dataclass, field
from decimal import Decimal

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ScreeningResult:
    """Normalised outcome of a screening request."""

    provider: str
    status: str  # "completed" | "pending" | "error"
    recommendation: str  # accept | review | decline | unknown
    credit_score: int | None = None
    external_ref: str | None = None
    report_data: dict = field(default_factory=dict)


def _configured() -> bool:
    return bool(getattr(settings, "SCREENING_API_KEY", None))


async def request_screening(
    *,
    first_name: str,
    last_name: str,
    email: str,
    monthly_income: Decimal | None = None,
) -> ScreeningResult:
    """Request a tenant-screening report for an applicant.

    When no screening provider is configured (the common dev/test case) a
    ``manual`` result is returned with a ``review`` recommendation so staff know
    to screen by hand — the funnel is never blocked on a missing integration.
    """
    if not _configured():
        logger.info("Screening skipped (provider not configured) for %s", email)
        return ScreeningResult(
            provider="manual",
            status="completed",
            recommendation="review",
            report_data={
                "note": "Screening provider not configured; manual review required.",
            },
        )

    provider = getattr(settings, "SCREENING_PROVIDER", "transunion") or "transunion"
    url = getattr(settings, "SCREENING_API_URL", "") or "https://api.example-screening.com/v1/reports"
    payload = {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "monthly_income": str(monthly_income) if monthly_income is not None else None,
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as http:
            resp = await http.post(
                url,
                json=payload,
                headers={"Authorization": "Bearer " + str(settings.SCREENING_API_KEY)},
            )
        if resp.status_code >= 400:
            logger.warning("Screening failed via %s: HTTP %s", provider, resp.status_code)
            return ScreeningResult(
                provider=provider, status="error", recommendation="unknown",
                report_data={"http_status": resp.status_code},
            )
        body = resp.json()
        return ScreeningResult(
            provider=provider,
            status="completed",
            recommendation=body.get("recommendation", "unknown"),
            credit_score=body.get("credit_score"),
            external_ref=body.get("id"),
            report_data=body,
        )
    except Exception as e:  # pragma: no cover - network failure path
        logger.warning("Screening error via %s: %s", provider, e)
        return ScreeningResult(
            provider=provider, status="error", recommendation="unknown",
            report_data={"error": str(e)},
        )
