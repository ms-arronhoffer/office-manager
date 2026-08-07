"""Tenant-screening client (Phase 2.4).

A thin, provider-agnostic wrapper around a third-party tenant-screening service
(credit / criminal / eviction checks). Like the SMS and payment clients, it
degrades gracefully when unconfigured: without ``SCREENING_API_KEY`` it returns a
``manual`` report flagged for staff review rather than calling out, so the leasing
funnel keeps working in dev/test without a live vendor.

Data minimisation
-----------------
A tenant-screening report obtained from a consumer reporting agency is a
*consumer report* under the Fair Credit Reporting Act. This module keeps only the
decision summary: see :data:`_SUMMARY_FIELDS` and :func:`summarize_report`. Raw
report bodies, Social Security numbers, full dates of birth, account/tradeline
detail and street addresses are dropped before the result is handed back, so they
never reach :class:`~app.models.leasing_funnel.ScreeningReport`.

FCRA obligations the operator still owns
----------------------------------------
Storing less is the part this code can enforce. The following are legal process,
not code, and remain the operator's responsibility:

* **Permissible purpose** (15 U.S.C. 1681b): only pull a report on an applicant
  who has given written authorisation for this specific tenancy decision.
* **Adverse-action notice** (15 U.S.C. 1681m): when a report contributes to a
  decline, the applicant must be told, in a notice naming the reporting agency,
  its address and phone number, stating that the agency did not make the
  decision, and setting out the applicant's right to a free copy of the report
  and to dispute its accuracy. :func:`build_adverse_action` assembles the
  reference data that notice needs; composing and sending it is the operator's
  job.
* **Dispute handling and reinvestigation** (15 U.S.C. 1681i): disputes are
  resolved with the reporting agency, not in this system.
* **Retention and secure disposal** (16 C.F.R. Part 682): purge stored summaries
  on the operator's documented retention schedule.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from decimal import Decimal

import httpx

from app.config import settings
from app.services.organization_integration_settings import ScreeningSettings, legacy_settings

logger = logging.getLogger(__name__)

# Canonical recommendations understood by the leasing funnel. Mirrors
# ``app.models.leasing_funnel.SCREENING_RECOMMENDATIONS``.
RECOMMENDATIONS = ("accept", "review", "decline", "unknown")

# Provider vocabularies mapped onto our canonical recommendations.
_RECOMMENDATION_ALIASES: dict[str, str] = {
    "accept": "accept",
    "accepted": "accept",
    "approve": "accept",
    "approved": "accept",
    "pass": "accept",
    "passed": "accept",
    "clear": "accept",
    "eligible": "accept",
    "review": "review",
    "manual_review": "review",
    "conditional": "review",
    "conditionally_approved": "review",
    "refer": "review",
    "pending_review": "review",
    "decline": "decline",
    "declined": "decline",
    "deny": "decline",
    "denied": "decline",
    "fail": "decline",
    "failed": "decline",
    "reject": "decline",
    "rejected": "decline",
    "ineligible": "decline",
}

# Provider status vocabularies mapped onto "completed" | "pending" | "error".
_STATUS_ALIASES: dict[str, str] = {
    "complete": "completed",
    "completed": "completed",
    "done": "completed",
    "finished": "completed",
    "ready": "completed",
    "success": "completed",
    "pending": "pending",
    "processing": "pending",
    "in_progress": "pending",
    "queued": "pending",
    "running": "pending",
    "submitted": "pending",
    "error": "error",
    "failed": "error",
    "failure": "error",
    "cancelled": "error",
    "canceled": "error",
    "expired": "error",
}

# Allowlist of decision-relevant summary keys copied out of a provider payload.
# An allowlist is used rather than a denylist of PII fields so an unrecognised
# provider field can never leak into storage.
_SUMMARY_FIELDS: tuple[str, ...] = (
    "credit_score_band",
    "score_band",
    "criminal_records_found",
    "eviction_records_found",
    "bankruptcy_records_found",
    "judgment_records_found",
    "collections_count",
    "late_payments_count",
    "income_to_rent_ratio",
    "income_verified",
    "identity_verified",
    "decision_reasons",
    "reason_codes",
    "completed_at",
    "report_type",
)

# Keys carrying the reporting agency's contact details, needed verbatim on an
# adverse-action notice.
_AGENCY_FIELDS: tuple[str, ...] = (
    "agency_name",
    "agency_phone",
    "agency_address",
    "agency_url",
)

_TERMINAL_STATUSES = frozenset({"completed", "error"})


@dataclass
class ScreeningResult:
    """Normalised outcome of a screening request."""

    provider: str
    status: str  # "completed" | "pending" | "error"
    recommendation: str  # accept | review | decline | unknown
    credit_score: int | None = None
    external_ref: str | None = None
    report_data: dict = field(default_factory=dict)
    # Populated only for a ``decline``: the reason codes and reporting-agency
    # reference an FCRA adverse-action notice must cite. Mirrored into
    # ``report_data["adverse_action"]`` so it persists on the existing JSONB
    # column without a schema change.
    adverse_action: dict | None = None


def _configured(config: ScreeningSettings) -> bool:
    return bool(config.is_enabled and config.api_key and config.api_url)


def _clean_str(value: object, limit: int = 200) -> str | None:
    """Coerce ``value`` to a trimmed, length-capped string, or ``None``."""
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def normalize_recommendation(raw: object) -> str:
    """Map a provider recommendation onto our canonical vocabulary."""
    key = str(raw).strip().lower().replace("-", "_").replace(" ", "_") if raw is not None else ""
    return _RECOMMENDATION_ALIASES.get(key, "unknown")


def normalize_status(raw: object) -> str:
    """Map a provider report status onto ``completed`` / ``pending`` / ``error``."""
    key = str(raw).strip().lower().replace("-", "_").replace(" ", "_") if raw is not None else ""
    return _STATUS_ALIASES.get(key, "pending")


def coerce_credit_score(raw: object) -> int | None:
    """Return a plausible credit score, or ``None``.

    Values outside 300-900 are discarded rather than stored, since a provider
    sentinel such as 0 or -1 would otherwise read as a real, very poor score.
    """
    if raw is None or isinstance(raw, bool):
        return None
    try:
        score = int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return None
    return score if 300 <= score <= 900 else None


def _reason_codes(body: dict) -> list[str]:
    """Extract decision reason codes from a provider payload."""
    raw = body.get("decision_reasons") or body.get("reason_codes") or body.get("reasons")
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []
    codes = [_clean_str(item) for item in raw]
    return [c for c in codes if c][:20]


def summarize_report(body: object) -> dict:
    """Reduce a provider payload to the FCRA-safe decision summary we persist.

    Only keys in :data:`_SUMMARY_FIELDS` survive. Raw report text, SSNs, dates of
    birth, addresses and tradeline detail are never copied, so they cannot reach
    the database through ``ScreeningReport.report_data``.
    """
    if not isinstance(body, dict):
        return {}
    summary: dict = {}
    for key in _SUMMARY_FIELDS:
        if key not in body:
            continue
        value = body[key]
        if isinstance(value, (bool, int, float)):
            summary[key] = value
        elif isinstance(value, (list, tuple)):
            items = [_clean_str(item) for item in value]
            summary[key] = [i for i in items if i][:20]
        else:
            cleaned = _clean_str(value)
            if cleaned is not None:
                summary[key] = cleaned
    return summary


def build_adverse_action(body: object, *, provider: str, external_ref: str | None) -> dict:
    """Assemble the reference data an FCRA adverse-action notice must cite.

    Returns the reason codes behind the decline plus the reporting agency's
    identity and contact details. The notice itself is composed and sent by the
    operator; this only records what it has to reference.
    """
    payload = body if isinstance(body, dict) else {}
    agency: dict = {}
    for key in _AGENCY_FIELDS:
        cleaned = _clean_str(payload.get(key))
        if cleaned is not None:
            agency[key] = cleaned
    agency.setdefault("agency_name", provider)
    return {
        "reason_codes": _reason_codes(payload),
        "provider": provider,
        "provider_reference": external_ref,
        "agency": agency,
        "notice_required": True,
    }


def normalize_screening_response(body: object, *, provider: str) -> ScreeningResult:
    """Turn a provider report payload into a :class:`ScreeningResult`.

    Pure and side-effect free so the normalisation rules can be tested without a
    network or a database.
    """
    if not isinstance(body, dict):
        return ScreeningResult(
            provider=provider,
            status="error",
            recommendation="unknown",
            report_data={"error": "Malformed provider response."},
        )

    external_ref = _clean_str(
        body.get("id") or body.get("report_id") or body.get("reference"), 100
    )
    status = normalize_status(body.get("status", "completed"))
    recommendation = normalize_recommendation(
        body.get("recommendation") or body.get("decision") or body.get("result")
    )
    # A report still in flight has no decision yet; never surface a stale one.
    if status == "pending":
        recommendation = "unknown"

    report_data = summarize_report(body)
    report_data["provider_status"] = _clean_str(body.get("status")) or status

    adverse_action = None
    if status == "completed" and recommendation == "decline":
        adverse_action = build_adverse_action(
            body, provider=provider, external_ref=external_ref
        )
        report_data["adverse_action"] = adverse_action

    return ScreeningResult(
        provider=provider,
        status=status,
        recommendation=recommendation,
        credit_score=coerce_credit_score(body.get("credit_score") or body.get("score")),
        external_ref=external_ref,
        report_data=report_data,
        adverse_action=adverse_action,
    )


def _manual_result() -> ScreeningResult:
    return ScreeningResult(
        provider="manual",
        status="completed",
        recommendation="review",
        report_data={
            "note": "Screening provider not configured; manual review required.",
        },
    )


def _base_url(config: ScreeningSettings) -> str:
    url = config.api_url or "https://api.example-screening.com/v1/reports"
    return url.rstrip("/")


def _headers(config: ScreeningSettings) -> dict[str, str]:
    return {
        "Authorization": "Bearer " + config.api_key,
        "Accept": "application/json",
    }


def _error_result(provider: str, detail: dict) -> ScreeningResult:
    return ScreeningResult(
        provider=provider, status="error", recommendation="unknown", report_data=detail
    )


async def _poll_report(
    http: httpx.AsyncClient,
    provider: str,
    report_id: str,
    attempts: int,
    interval: float,
    config: ScreeningSettings,
) -> ScreeningResult:
    """Poll a submitted report until it is terminal or the attempts run out."""
    result = ScreeningResult(
        provider=provider,
        status="pending",
        recommendation="unknown",
        external_ref=report_id,
    )
    for attempt in range(attempts):
        await asyncio.sleep(interval)
        resp = await http.get(f"{_base_url(config)}/{report_id}", headers=_headers(config))
        if resp.status_code >= 400:
            logger.warning(
                "Screening poll failed via %s: HTTP %s (attempt %s)",
                provider, resp.status_code, attempt + 1,
            )
            return _error_result(
                provider, {"http_status": resp.status_code, "stage": "poll"}
            )
        result = normalize_screening_response(resp.json(), provider=provider)
        if result.status in _TERMINAL_STATUSES:
            return result
    logger.info("Screening still pending via %s after %s polls", provider, attempts)
    return result


async def request_screening(
    *,
    first_name: str,
    last_name: str,
    email: str,
    monthly_income: Decimal | None = None,
    config: ScreeningSettings | None = None,
) -> ScreeningResult:
    """Request a tenant-screening report for an applicant.

    Submits the applicant to the configured provider and, when the provider
    answers asynchronously, polls until the report reaches a terminal state.
    Only the identifiers the caller supplied are sent, so no SSN or date of birth
    passes through this client, and the response is reduced to a decision summary
    before it is returned (see :func:`summarize_report`).

    When no screening provider is configured (the common dev/test case) a
    ``manual`` result is returned with a ``review`` recommendation so staff know
    to screen by hand, and the funnel is never blocked on a missing integration.
    """
    config = config or legacy_settings("screening")
    if not _configured(config):
        logger.info("Screening skipped (provider not configured) for %s", email)
        return _manual_result()

    provider = config.provider_name
    attempts = config.poll_attempts
    interval = config.poll_interval_seconds
    payload = {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "monthly_income": str(monthly_income) if monthly_income is not None else None,
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as http:
            resp = await http.post(_base_url(config), json=payload, headers=_headers(config))
            if resp.status_code >= 400:
                logger.warning(
                    "Screening failed via %s: HTTP %s", provider, resp.status_code
                )
                return _error_result(
                    provider, {"http_status": resp.status_code, "stage": "submit"}
                )

            result = normalize_screening_response(resp.json(), provider=provider)
            if result.status == "pending" and result.external_ref and attempts > 0:
                result = await _poll_report(
                    http, provider, result.external_ref, attempts, interval, config
                )
        return result
    except Exception as e:  # pragma: no cover - network failure path
        logger.warning("Screening error via %s: %s", provider, e)
        return _error_result(provider, {"error": str(e)})
