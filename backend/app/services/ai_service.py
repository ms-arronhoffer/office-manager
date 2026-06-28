"""Google Gemini integration for SwiftLease AI-assist features.

This is a thin async client over the Gemini ``generateContent`` REST endpoint.
It deliberately avoids a heavy vendored SDK and instead uses ``httpx`` (already a
project dependency) so the model id, API key, and base endpoint stay fully
configurable through environment variables (``GEMINI_MODEL``, ``GEMINI_API_KEY``,
``GEMINI_API_BASE``).

Design notes:

* **Graceful degradation** — when ``GEMINI_API_KEY`` is unset every public
  helper raises :class:`AIUnavailableError`, which the router translates into a
  clear ``503``. Nothing crashes and no network call is attempted. This mirrors
  how SMTP/Stripe degrade elsewhere in the codebase.
* **Structured output** — extraction helpers ask Gemini for JSON
  (``responseMimeType: application/json``) and parse it defensively so the
  result maps cleanly onto existing Pydantic schemas.
* **Async + bounded** — calls run through an async ``httpx`` client with a
  configurable timeout so request worker threads are never blocked indefinitely.

All helpers return *suggestions* for human review; callers never auto-commit
AI output.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Hard caps to protect against oversized prompts / documents.
MAX_DOCUMENT_BYTES = 15 * 1024 * 1024  # 15 MB of raw document bytes
MAX_TEXT_CHARS = 200_000


class AIError(Exception):
    """Base class for AI-assist failures."""


class AIUnavailableError(AIError):
    """Raised when the AI provider is not configured (no API key)."""


class AIRequestError(AIError):
    """Raised when the provider call fails or returns an unusable response."""


def is_configured() -> bool:
    """Return whether a Gemini API key is configured."""
    return bool(settings.GEMINI_API_KEY)


def _endpoint() -> str:
    base = settings.GEMINI_API_BASE.rstrip("/")
    model = settings.GEMINI_MODEL
    return f"{base}/models/{model}:generateContent"


def _require_configured() -> None:
    if not is_configured():
        raise AIUnavailableError(
            "AI assist is not configured. Set GEMINI_API_KEY to enable it."
        )


async def _generate(
    parts: list[dict[str, Any]],
    *,
    system_instruction: str | None = None,
    json_response: bool = False,
    temperature: float = 0.2,
) -> str:
    """Call Gemini ``generateContent`` and return the first text part.

    ``parts`` is the list of content parts (text and/or inline document data).
    """
    _require_configured()

    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"temperature": temperature},
    }
    if system_instruction:
        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
    if json_response:
        payload["generationConfig"]["responseMimeType"] = "application/json"

    url = _endpoint()
    try:
        async with httpx.AsyncClient(timeout=settings.GEMINI_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                url,
                params={"key": settings.GEMINI_API_KEY},
                json=payload,
            )
    except httpx.HTTPError as exc:  # network/timeout
        logger.warning("Gemini request failed: %s", exc)
        raise AIRequestError(f"AI provider request failed: {exc}") from exc

    if resp.status_code != 200:
        # Avoid leaking the API key; surface only the status + provider message.
        detail = _safe_error_detail(resp)
        logger.warning("Gemini returned %s: %s", resp.status_code, detail)
        raise AIRequestError(f"AI provider error ({resp.status_code}): {detail}")

    try:
        data = resp.json()
        candidates = data.get("candidates") or []
        first = candidates[0]
        out_parts = first["content"]["parts"]
        text = "".join(p.get("text", "") for p in out_parts)
    except (KeyError, IndexError, ValueError) as exc:
        logger.warning("Unexpected Gemini response shape: %s", exc)
        raise AIRequestError("AI provider returned an unexpected response") from exc

    if not text.strip():
        raise AIRequestError("AI provider returned an empty response")
    return text


def _safe_error_detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        msg = body.get("error", {}).get("message")
        if msg:
            return str(msg)
    except ValueError:
        pass
    return resp.reason_phrase or "unknown error"


def _parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from a model response, tolerating code fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Strip ```json ... ``` fences if the model added them.
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise AIRequestError("AI provider did not return valid JSON") from exc
    if not isinstance(result, dict):
        raise AIRequestError("AI provider returned JSON that was not an object")
    return result


def _document_part(content: bytes, mime_type: str) -> dict[str, Any]:
    if len(content) > MAX_DOCUMENT_BYTES:
        raise AIRequestError(
            f"Document is too large for AI processing "
            f"(max {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB)."
        )
    return {
        "inlineData": {
            "mimeType": mime_type,
            "data": base64.b64encode(content).decode("ascii"),
        }
    }


# ── Public helpers ────────────────────────────────────────────────────────────

LEASE_PARSE_SYSTEM = (
    "You are a commercial real-estate lease abstraction assistant. Extract key "
    "lease details from the supplied document. Respond ONLY with a JSON object. "
    "Use null for any field you cannot determine. Dates must be ISO 8601 "
    "(YYYY-MM-DD). Do not invent values.\n"
    "\n"
    "Financial extraction rules:\n"
    "- Return all monetary amounts as plain numbers (no currency symbols, commas, "
    "or thousands separators), e.g. 12500.50 not \"$12,500.50\".\n"
    "- payment_amount must be the base rent for ONE payment_frequency period. If "
    "the lease states an annual base rent but rent is paid monthly, divide by 12 "
    "and set payment_frequency to monthly. If it states a per-square-foot rate, "
    "multiply by the rentable area to get the periodic amount when the area is "
    "given.\n"
    "- Express rates (annual_escalation_rate, incremental_borrowing_rate) as "
    "decimal fractions, e.g. 3% becomes 0.03 and 4.5% becomes 0.045.\n"
    "- Prefer the most recent/initial base rent at commencement when a rent "
    "schedule lists multiple steps."
)

# The fields we ask Gemini to populate map directly onto LeaseCreate (including
# the ASC 842 / IFRS 16 accounting & financial terms).
LEASE_PARSE_FIELDS = {
    "lease_name": "Short human name for the lease, e.g. tenant or suite",
    "lessor_name": "The landlord / lessor legal name",
    "lease_commencement_date": "Commencement date (YYYY-MM-DD)",
    "lease_expiration": "Expiration / termination date (YYYY-MM-DD)",
    "lease_notice_date": "Date by which renewal/termination notice must be given (YYYY-MM-DD)",
    "notice_period": "Notice period as written, e.g. '90 days'",
    "notice_period_days": "Notice period in whole days (integer)",
    "expiration_year": "Year the lease expires (integer)",
    # ── Accounting & financial terms (ASC 842 / IFRS 16) ──────────────────────
    "payment_amount": "Base rent for a SINGLE payment period as a plain number (no symbols/commas), matching payment_frequency",
    "payment_frequency": "Billing cadence of the base rent: one of monthly, quarterly, annually",
    "annual_escalation_rate": "Annual rent escalation as a decimal fraction, e.g. 0.03 for 3%",
    "accounting_standard": "Accounting standard if stated: one of asc842, ifrs16, both",
    "lease_classification": "Lease classification if determinable: operating or finance",
    "incremental_borrowing_rate": "Incremental borrowing / discount rate as a decimal fraction, e.g. 0.045 for 4.5%",
    "initial_direct_costs": "Initial direct costs capitalised at commencement as a plain number",
    "lease_incentives": "Lease incentives / tenant improvement allowances received from the lessor as a plain number",
    "prepaid_rent": "Prepaid rent paid at or before commencement as a plain number",
    "residual_value_guarantee": "Residual value guaranteed by the lessee as a plain number",
    "is_short_term_lease": "True if the total lease term is 12 months or less (boolean)",
    "is_low_value_lease": "True if the underlying asset is low-value (boolean)",
    "currency": "ISO 4217 currency code of the payments, e.g. USD",
}


async def parse_lease_document(
    content: bytes,
    mime_type: str,
    *,
    text_content: str | None = None,
) -> dict[str, Any]:
    """Extract structured lease fields from a document.

    For PDFs and images the raw bytes are sent inline (Gemini reads them
    natively). For formats Gemini cannot parse directly (e.g. Word documents),
    the caller extracts plain text first and passes it as ``text_content``; that
    text is then sent in place of the inline document.

    Returns a dict whose keys are a subset of :class:`LeaseCreate` fields.
    """
    field_spec = "\n".join(f"- {k}: {v}" for k, v in LEASE_PARSE_FIELDS.items())
    prompt = (
        "Extract the following fields from the lease document and "
        "return a single JSON object with exactly these keys:\n"
        f"{field_spec}\n"
    )
    if text_content is not None:
        document = text_content[:MAX_TEXT_CHARS].strip()
        if not document:
            raise AIRequestError("The document did not contain any readable text.")
        parts = [
            {"text": prompt},
            {"text": "\n\nLEASE DOCUMENT TEXT:\n" + document},
        ]
    else:
        parts = [{"text": prompt}, _document_part(content, mime_type)]
    text = await _generate(
        parts, system_instruction=LEASE_PARSE_SYSTEM, json_response=True
    )
    return _parse_json_object(text)


ABSTRACT_SUGGEST_SYSTEM = (
    "You are a commercial lease abstraction assistant. For each requested clause "
    "category, extract the relevant lease provisions into the category's "
    "structured fields, and also summarise them concisely and factually. "
    "Respond ONLY with a JSON object keyed by category_key; each value is an "
    "object whose keys are the field keys listed for that category. Populate "
    "every field you can from the document, putting discrete values in their "
    "dedicated fields (e.g. a 60-day notice period belongs in the notice-days "
    "field, not only the summary). Match each field's type: 'number'/'currency'/"
    "'percent' as JSON numbers (digits only, no units or symbols), 'boolean' as "
    "true/false, 'date' as 'YYYY-MM-DD', 'select' as one of the provided options, "
    "and 'text'/'textarea' as strings. Always include a 'summary' field "
    "summarising the category and a 'notes' field for any extra narrative. Omit "
    "fields the document does not address (or use an empty string). Never invent "
    "terms or values that are not in the document."
)


def _format_category_fields(category: dict[str, Any]) -> str:
    """Render a category's field schema as a prompt bullet list."""
    lines: list[str] = []
    for field in category.get("fields", []):
        ftype = field.get("type", "text")
        descriptor = f"    - {field['key']} ({ftype}): {field['label']}"
        options = field.get("options")
        if options:
            descriptor += f" [one of: {', '.join(options)}]"
        lines.append(descriptor)
    return "\n".join(lines)


async def suggest_abstract_clauses(
    content: bytes,
    mime_type: str,
    categories: list[dict[str, Any]],
    *,
    text_content: str | None = None,
) -> dict[str, Any]:
    """Propose lease-abstract clause content per category.

    ``categories`` is a list of ``{"key": ..., "name": ..., "fields": [...]}``
    dicts taken from the lease-abstract catalog, where each field is a
    ``{"key", "label", "type", "options"?}`` schema. Returns a dict keyed by
    category key whose values map field keys to extracted values.

    For PDFs and images the raw bytes are sent inline (Gemini reads them
    natively). For formats Gemini cannot parse directly (e.g. Word/text
    documents), the caller extracts plain text first and passes it as
    ``text_content``; that text is sent in place of the inline document.
    """
    cat_blocks: list[str] = []
    for c in categories:
        block = f"- {c['key']}: {c['name']}"
        fields = _format_category_fields(c)
        if fields:
            block += "\n  fields:\n" + fields
        cat_blocks.append(block)
    cat_spec = "\n".join(cat_blocks)
    prompt = (
        "Abstract the lease into structured fields for each of these clause "
        "categories. Each category lists its field keys, types, and labels; "
        "return a JSON object per category keyed by those field keys:\n"
        f"{cat_spec}\n"
    )
    if text_content is not None:
        document = text_content[:MAX_TEXT_CHARS].strip()
        if not document:
            raise AIRequestError("The document did not contain any readable text.")
        parts = [
            {"text": prompt},
            {"text": "\n\nLEASE DOCUMENT TEXT:\n" + document},
        ]
    else:
        parts = [{"text": prompt}, _document_part(content, mime_type)]
    text = await _generate(
        parts, system_instruction=ABSTRACT_SUGGEST_SYSTEM, json_response=True
    )
    return _parse_json_object(text)


# ── Inbound document classification & routing ────────────────────────────────

# The document types we can classify inbound items into. ``unknown`` is the
# catch-all when the model cannot confidently place a document.
INBOUND_DOCUMENT_TYPES = (
    "vendor_invoice",
    "insurance_certificate",
    "lease_amendment",
    "lease",
    "unknown",
)

_CLASSIFY_CONFIDENCES = ("high", "medium", "low")

# Per-type field schemas the model extracts to pre-fill the matching record.
# These map onto VendorBill, InsuranceCertificate, and Lease fields respectively.
INBOUND_CLASSIFY_FIELDS: dict[str, dict[str, str]] = {
    "vendor_invoice": {
        "vendor_name": "Name of the vendor / supplier that issued the invoice",
        "bill_number": "The vendor's invoice or bill number as printed",
        "bill_date": "Invoice/bill date (YYYY-MM-DD)",
        "due_date": "Payment due date (YYYY-MM-DD)",
        "total_amount": "Invoice total as a plain number (no symbols/commas)",
        "currency": "ISO 4217 currency code of the amount, e.g. USD",
        "memo": "Short description of what the invoice is for",
    },
    "insurance_certificate": {
        "insured_name": "The named insured the certificate covers (usually the vendor or landlord)",
        "certificate_type": "One of: general_liability, workers_comp, auto, umbrella, other",
        "insurer": "The insurance carrier / company providing coverage",
        "policy_number": "The policy number as printed",
        "effective_date": "Coverage effective date (YYYY-MM-DD)",
        "expiration_date": "Coverage expiration date (YYYY-MM-DD)",
        "limits": "Coverage limits as written, e.g. '$1,000,000 each occurrence'",
        "certificate_holder": "The certificate holder named on the COI",
    },
    "lease_amendment": {
        "lease_name": "Short name of the lease being amended (tenant/suite if present)",
        "lessor_name": "The landlord / lessor legal name on the amendment",
        "amendment_type": "Nature of the amendment: one of extension, rent_change, expansion, contraction, termination, other",
        "effective_date": "Date the amendment takes effect (YYYY-MM-DD)",
        "new_expiration_date": "New lease expiration date if the amendment changes it (YYYY-MM-DD)",
        "new_payment_amount": "New periodic base rent if the amendment changes it, as a plain number",
        "summary": "One or two sentence factual summary of what the amendment changes",
    },
    "lease": {
        "lease_name": "Short human name for the lease, e.g. tenant or suite",
        "lessor_name": "The landlord / lessor legal name",
        "lease_commencement_date": "Commencement date (YYYY-MM-DD)",
        "lease_expiration": "Expiration / termination date (YYYY-MM-DD)",
        "payment_amount": "Base rent for a SINGLE payment period as a plain number",
        "payment_frequency": "Billing cadence of the base rent: one of monthly, quarterly, annually",
    },
}

INBOUND_CLASSIFY_SYSTEM = (
    "You are a back-office assistant for a commercial property management team "
    "that triages inbound documents (emails and their attachments). Determine "
    "which single type best describes the document, then extract that type's "
    "fields so a human can route and pre-fill the matching record. Respond ONLY "
    "with a JSON object. Do not invent values.\n"
    "\n"
    "Document types:\n"
    "- vendor_invoice: a bill/invoice received from a vendor or supplier (AP).\n"
    "- insurance_certificate: a certificate of insurance (COI / ACORD form).\n"
    "- lease_amendment: an amendment, addendum, extension, or modification to an "
    "existing lease.\n"
    "- lease: a new/original lease agreement.\n"
    "- unknown: none of the above, or too ambiguous to classify confidently.\n"
    "\n"
    "Rules:\n"
    "- document_type must be exactly one of: vendor_invoice, "
    "insurance_certificate, lease_amendment, lease, unknown.\n"
    "- confidence must be exactly one of: high, medium, low.\n"
    "- reasoning must be one short sentence explaining the classification.\n"
    "- fields must be a JSON object containing ONLY the keys listed for the "
    "chosen document_type (an empty object for 'unknown'). Use null for any "
    "field you cannot determine.\n"
    "- Dates must be ISO 8601 (YYYY-MM-DD). Return monetary amounts as plain "
    "numbers with no currency symbols, commas, or thousands separators."
)


def _format_classify_fields() -> str:
    """Render the per-type field schema as a prompt block."""
    blocks: list[str] = []
    for doc_type, fields in INBOUND_CLASSIFY_FIELDS.items():
        lines = "\n".join(f"    - {k}: {v}" for k, v in fields.items())
        blocks.append(f"- {doc_type}:\n{lines}")
    return "\n".join(blocks)


async def classify_document(
    content: bytes,
    mime_type: str,
    *,
    text_content: str | None = None,
) -> dict[str, Any]:
    """Classify an inbound document and extract type-specific fields.

    Returns a dict with the keys ``document_type`` (one of
    :data:`INBOUND_DOCUMENT_TYPES`), ``confidence`` (high/medium/low),
    ``reasoning`` (a short string) and ``fields`` (the extracted values for the
    detected type). All values are *suggestions* for human review; callers never
    auto-commit.

    For PDFs and images the raw bytes are sent inline (Gemini reads them
    natively). For formats Gemini cannot parse directly (e.g. Word/text
    documents), the caller extracts plain text first and passes it as
    ``text_content``; that text is sent in place of the inline document.
    """
    prompt = (
        "Classify the following inbound document and extract the fields for the "
        "detected type. Return a single JSON object with exactly these keys: "
        "document_type, confidence, reasoning, fields.\n\n"
        "DOCUMENT TYPES AND THEIR FIELDS:\n"
        f"{_format_classify_fields()}\n"
    )
    if text_content is not None:
        document = text_content[:MAX_TEXT_CHARS].strip()
        if not document:
            raise AIRequestError("The document did not contain any readable text.")
        parts = [
            {"text": prompt},
            {"text": "\n\nDOCUMENT TEXT:\n" + document},
        ]
    else:
        parts = [{"text": prompt}, _document_part(content, mime_type)]
    text = await _generate(
        parts, system_instruction=INBOUND_CLASSIFY_SYSTEM, json_response=True
    )
    return _normalize_classification(_parse_json_object(text))


def _normalize_classification(parsed: dict[str, Any]) -> dict[str, Any]:
    """Coerce raw model output into a clean classification result.

    Unknown/invalid document types collapse to ``unknown`` and the returned
    ``fields`` are restricted to the keys defined for the detected type so
    callers can map them onto the right record without surprises.
    """
    doc_type = str(parsed.get("document_type") or "").strip().lower()
    if doc_type not in INBOUND_DOCUMENT_TYPES:
        doc_type = "unknown"

    confidence = str(parsed.get("confidence") or "").strip().lower()
    if confidence not in _CLASSIFY_CONFIDENCES:
        confidence = "low"

    allowed = INBOUND_CLASSIFY_FIELDS.get(doc_type, {})
    raw_fields = parsed.get("fields")
    fields: dict[str, Any] = {}
    if isinstance(raw_fields, dict):
        fields = {k: raw_fields.get(k) for k in allowed if k in raw_fields}

    return {
        "document_type": doc_type,
        "confidence": confidence,
        "reasoning": str(parsed.get("reasoning") or "").strip()[:500],
        "fields": fields,
    }


TICKET_TRIAGE_SYSTEM = (
    "You are a dispatcher for a commercial property maintenance team. Given a "
    "maintenance request (subject + description) and the lists of available "
    "ticket categories and vendors, recommend how to triage the request. "
    "Respond ONLY with a JSON object. Do not invent categories, vendors, or "
    "values that are not provided.\n"
    "\n"
    "Rules:\n"
    "- category_id must be the id of the single best-matching category from the "
    "supplied list, or null if none clearly fit. category_name must be that "
    "category's name (or null).\n"
    "- priority must be exactly one of: low, medium, high. Use high for safety "
    "issues, security, no heat/AC, water leaks, power loss, or anything blocking "
    "business operations; medium for problems that impair use but are not "
    "urgent; low for cosmetic or routine requests.\n"
    "- vendor_id must be the id of the most suitable vendor from the supplied "
    "list based on the vendor's services/trade, or null if none clearly fit. "
    "Prefer a vendor marked preferred when two are equally suitable. vendor_name "
    "must be that vendor's company name (or null).\n"
    "- reasoning must be one short sentence explaining the recommendation.\n"
    "- draft_response must be a brief, professional acknowledgement message the "
    "team could send to the requester, confirming the issue and next steps."
)


async def triage_ticket(
    subject: str,
    description: str,
    categories: list[dict[str, Any]],
    vendors: list[dict[str, Any]],
) -> dict[str, Any]:
    """Recommend triage details for a maintenance ticket.

    ``categories`` is a list of ``{"id", "name"}`` dicts and ``vendors`` a list
    of ``{"id", "name", "services", "preferred"}`` dicts (both organization
    scoped by the caller). Returns a dict with the keys ``category_id``,
    ``category_name``, ``priority``, ``vendor_id``, ``vendor_name``,
    ``reasoning`` and ``draft_response``. All values are *suggestions* for human
    review; callers never auto-assign.
    """
    cat_lines = "\n".join(f"- {c['id']}: {c['name']}" for c in categories) or "(none)"
    vendor_lines = (
        "\n".join(
            "- {id}: {name}{services}{preferred}".format(
                id=v["id"],
                name=v["name"],
                services=f" — services: {v['services']}" if v.get("services") else "",
                preferred=" [preferred]" if v.get("preferred") else "",
            )
            for v in vendors
        )
        or "(none)"
    )
    prompt = (
        "Triage this maintenance request and return a single JSON object with "
        "exactly these keys: category_id, category_name, priority, vendor_id, "
        "vendor_name, reasoning, draft_response.\n\n"
        f"SUBJECT:\n{(subject or '').strip()[:2000]}\n\n"
        f"DESCRIPTION:\n{(description or '').strip()[:MAX_TEXT_CHARS]}\n\n"
        f"AVAILABLE CATEGORIES (id: name):\n{cat_lines}\n\n"
        f"AVAILABLE VENDORS (id: name — services):\n{vendor_lines}\n"
    )
    text = await _generate(
        [{"text": prompt}],
        system_instruction=TICKET_TRIAGE_SYSTEM,
        json_response=True,
    )
    return _parse_json_object(text)


SUMMARY_SYSTEM = (
    "You are an operations analyst for a commercial property management team. "
    "Write a concise, professional briefing in Markdown from the structured data "
    "provided. Lead with the most time-sensitive items, covering, where present: "
    "lease notice deadlines, upcoming lease expirations, overdue maintenance, "
    "expiring certificates of insurance (COIs), upcoming HVAC service/contract "
    "renewals, and past-due accounts-payable (vendor bills). Be specific and do "
    "not invent data beyond what is given."
)


async def generate_summary_narrative(period_label: str, data: dict[str, Any]) -> str:
    """Generate a narrative summary report from aggregated stats.

    ``data`` is a JSON-serialisable dict of pre-aggregated figures (counts,
    upcoming lease notice/expiration items, overdue tickets, expiring COIs,
    HVAC renewals, past-due payables, etc).
    """
    blob = json.dumps(data, default=str)
    if len(blob) > MAX_TEXT_CHARS:
        blob = blob[:MAX_TEXT_CHARS]
    prompt = (
        f"Write a portfolio operations summary for the period: {period_label}.\n"
        "Use the following structured data (JSON):\n"
        f"{blob}\n"
    )
    parts = [{"text": prompt}]
    return await _generate(parts, system_instruction=SUMMARY_SYSTEM, temperature=0.4)


# ── AI-recommended actions ────────────────────────────────────────────────────

RECOMMENDED_ACTIONS_SYSTEM = (
    "You are an operations analyst for a commercial property management team. "
    "From the structured portfolio data provided, produce a prioritised list of "
    "concrete, actionable next steps the team should take this period. Focus on "
    "time-sensitive risk and deadline items: lease notice deadlines and "
    "expirations, overdue maintenance, expiring certificates of insurance (COIs), "
    "upcoming HVAC service/contract renewals, and past-due vendor bills. "
    "Return ONLY a JSON object of the form "
    '{"actions": [{"title": "...", "detail": "...", "priority": "high|medium|low", '
    '"category": "lease|insurance|hvac|accounts_payable|maintenance|other"}]}. '
    "Order actions from highest to lowest priority. Keep each title short (under "
    "120 characters) and the detail to one or two sentences. Do not invent data "
    "beyond what is given; if nothing requires action, return an empty list."
)

# Bound how many actions we surface so the prompt/response stay manageable.
MAX_RECOMMENDED_ACTIONS = 12

_ACTION_PRIORITIES = ("high", "medium", "low")


async def generate_recommended_actions(
    period_label: str, data: dict[str, Any]
) -> list[dict[str, Any]]:
    """Generate a structured list of AI-recommended actions from aggregated stats.

    Returns a list of ``{"title", "detail", "priority", "category"}`` dicts,
    ordered highest-priority first. Defensive against malformed model output.
    """
    blob = json.dumps(data, default=str)
    if len(blob) > MAX_TEXT_CHARS:
        blob = blob[:MAX_TEXT_CHARS]
    prompt = (
        f"Recommend prioritised actions for the period: {period_label}.\n"
        "Use the following structured data (JSON):\n"
        f"{blob}\n"
    )
    parts = [{"text": prompt}]
    raw = await _generate(
        parts,
        system_instruction=RECOMMENDED_ACTIONS_SYSTEM,
        json_response=True,
        temperature=0.3,
    )
    parsed = _parse_json_object(raw)
    return _normalize_actions(parsed.get("actions"))


def _normalize_actions(actions: Any) -> list[dict[str, Any]]:
    """Coerce model output into a clean, bounded list of action dicts."""
    if not isinstance(actions, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for item in actions:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        priority = str(item.get("priority") or "").strip().lower()
        if priority not in _ACTION_PRIORITIES:
            priority = "medium"
        category = str(item.get("category") or "other").strip().lower() or "other"
        cleaned.append(
            {
                "title": title[:200],
                "detail": str(item.get("detail") or "").strip()[:500],
                "priority": priority,
                "category": category,
            }
        )
        if len(cleaned) >= MAX_RECOMMENDED_ACTIONS:
            break
    return cleaned


def actions_to_markdown(actions: list[dict[str, Any]]) -> str:
    """Render recommended actions as a Markdown section for emails/exports."""
    if not actions:
        return ""
    lines = ["## AI-Recommended Actions", ""]
    for action in actions:
        priority = str(action.get("priority") or "medium").upper()
        title = str(action.get("title") or "").strip()
        detail = str(action.get("detail") or "").strip()
        bullet = f"- **[{priority}] {title}**"
        if detail:
            bullet += f" — {detail}"
        lines.append(bullet)
    return "\n".join(lines)


# ── Portfolio Q&A (RAG over lease document chunks) ───────────────────────────

PORTFOLIO_QA_SYSTEM = (
    "You are a commercial real-estate portfolio analyst assistant. Answer the "
    "user's question using ONLY the supplied lease document excerpts. Each "
    "excerpt is prefixed with a numbered citation id like [1], [2]. Ground every "
    "factual claim in the excerpts and cite the supporting excerpt id(s) inline "
    "in square brackets, e.g. 'the lease expires in 2026 [2].'. Cite only "
    "excerpts you actually relied on. If the excerpts do not contain enough "
    "information to answer the question, say so plainly — do not speculate or "
    "invent lease terms, dates, or figures. Be concise and use Markdown."
)

# Cap how many excerpts (and how much of each) we feed the model so the prompt
# stays bounded regardless of how many chunks were retrieved.
MAX_QA_CONTEXT_CHUNKS = 12
MAX_QA_CHUNK_CHARS = 4000


async def answer_portfolio_question(
    question: str,
    context_chunks: list[dict[str, Any]],
    *,
    temperature: float = 0.2,
) -> str:
    """Answer ``question`` grounded in retrieved lease document excerpts.

    ``context_chunks`` is an ordered list of dicts describing the retrieved
    excerpts. Each must carry an ``index`` (1-based citation id) and a textual
    body (``content`` or ``snippet``); ``lease_name`` and ``source_filename``
    are included in the prompt when present so the model can attribute claims.
    The returned Markdown answer cites excerpts inline by their ``index``.

    Raises :class:`AIUnavailableError` when no API key is configured so callers
    can degrade gracefully.
    """
    question = (question or "").strip()
    if not question:
        raise AIRequestError("A question is required.")

    blocks: list[str] = []
    for chunk in context_chunks[:MAX_QA_CONTEXT_CHUNKS]:
        idx = chunk.get("index")
        body = (chunk.get("content") or chunk.get("snippet") or "").strip()
        if idx is None or not body:
            continue
        lease_name = (chunk.get("lease_name") or "Unknown lease").strip()
        filename = (chunk.get("source_filename") or "").strip()
        header = f"[{idx}] Lease: {lease_name}"
        if filename:
            header += f" — Document: {filename}"
        blocks.append(f"{header}\n{body[:MAX_QA_CHUNK_CHARS]}")

    if not blocks:
        raise AIRequestError("No lease document excerpts were available to answer the question.")

    context = "\n\n".join(blocks)[:MAX_TEXT_CHARS]
    prompt = (
        f"QUESTION:\n{question}\n\n"
        "LEASE DOCUMENT EXCERPTS:\n"
        f"{context}\n\n"
        "Answer the question using only these excerpts and cite the excerpt "
        "id(s) you used in square brackets."
    )
    return await _generate(
        [{"text": prompt}],
        system_instruction=PORTFOLIO_QA_SYSTEM,
        temperature=temperature,
    )


# ── Embeddings (semantic document search) ─────────────────────────────────────

# Cap the number of texts embedded in a single batch request.
EMBED_BATCH_SIZE = 100


def _embed_endpoint(model: str) -> str:
    base = settings.GEMINI_API_BASE.rstrip("/")
    return f"{base}/models/{model}:batchEmbedContents"


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Return an embedding vector for each input string via Gemini.

    Raises :class:`AIUnavailableError` when no API key is configured so callers
    can fall back to keyword search. The embedding model is configurable via
    ``GEMINI_EMBED_MODEL``.
    """
    _require_configured()
    if not texts:
        return []

    model = settings.GEMINI_EMBED_MODEL
    url = _embed_endpoint(model)
    vectors: list[list[float]] = []

    for start in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[start : start + EMBED_BATCH_SIZE]
        payload = {
            "requests": [
                {
                    "model": f"models/{model}",
                    "content": {"parts": [{"text": (t or "")[:MAX_TEXT_CHARS]}]},
                }
                for t in batch
            ]
        }
        try:
            async with httpx.AsyncClient(timeout=settings.GEMINI_TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    url, params={"key": settings.GEMINI_API_KEY}, json=payload
                )
        except httpx.HTTPError as exc:
            logger.warning("Gemini embed request failed: %s", exc)
            raise AIRequestError(f"AI provider request failed: {exc}") from exc

        if resp.status_code != 200:
            detail = _safe_error_detail(resp)
            logger.warning("Gemini embed returned %s: %s", resp.status_code, detail)
            raise AIRequestError(f"AI provider error ({resp.status_code}): {detail}")

        try:
            data = resp.json()
            embeddings = data["embeddings"]
            for emb in embeddings:
                vectors.append([float(v) for v in emb["values"]])
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Unexpected Gemini embed response shape: %s", exc)
            raise AIRequestError("AI provider returned an unexpected response") from exc

    return vectors
