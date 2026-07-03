"""Leasing funnel service layer (Phase 2.4).

Holds the funnel rules so the ``/api/v1/leasing-funnel`` router stays thin:

  - rental application intake, review transitions, and conversion to a resident
  - tenant screening via the pluggable :mod:`app.utils.screening_client`
  - full-lease e-signing that extends the waiver/e-signature engine
    (:mod:`app.services.waiver_service`) to multi-party lease documents

Lease e-sign reuses the waiver primitives (``render_body``,
``compute_document_hash``, ``ESIGN_CONSENT_TEXT``, ``generate_signed_pdf``) so the
signed lease carries the same tamper-evident hash and ESIGN/UETA audit trail as a
signed waiver, while supporting several signing parties per document.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.leasing_funnel import (
    LeaseSignatureParty,
    LeaseSignatureRequest,
    RentalApplication,
    ScreeningReport,
)
from app.models.resident import Resident
from app.services import waiver_service
from app.utils import screening_client


class FunnelError(ValueError):
    """Raised for leasing-funnel rule violations."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

# Allowed application status transitions (from -> {to}).
_APP_TRANSITIONS: dict[str, set[str]] = {
    "submitted": {"screening", "approved", "denied", "withdrawn"},
    "screening": {"approved", "denied", "withdrawn"},
    "approved": {"converted", "withdrawn"},
    "denied": set(),
    "withdrawn": set(),
    "converted": set(),
}


def can_transition(current: str, target: str) -> bool:
    return target in _APP_TRANSITIONS.get(current, set())


async def set_application_status(
    db: AsyncSession,
    application: RentalApplication,
    target: str,
    *,
    decided_by_id: uuid.UUID | None = None,
    decision_notes: str | None = None,
) -> RentalApplication:
    """Move an application to ``target``, enforcing the workflow."""
    if application.status == target:
        return application
    if not can_transition(application.status, target):
        raise FunnelError(
            f"Cannot move an application from '{application.status}' to '{target}'."
        )
    application.status = target
    if target in ("approved", "denied"):
        application.decided_at = _now()
        application.decided_by_id = decided_by_id
        if decision_notes is not None:
            application.decision_notes = decision_notes
    return application


async def convert_to_resident(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    application: RentalApplication,
) -> Resident:
    """Create (or reuse) a resident record from an approved application."""
    if application.status != "approved":
        raise FunnelError("Only an approved application can be converted to a resident.")
    if application.resident_id:
        existing = (
            await db.execute(
                select(Resident).where(Resident.id == application.resident_id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    resident = Resident(
        organization_id=organization_id,
        first_name=application.applicant_first_name,
        last_name=application.applicant_last_name,
        email=application.applicant_email,
        phone=application.applicant_phone,
        status="prospect",
    )
    db.add(resident)
    await db.flush()
    application.resident_id = resident.id
    application.status = "converted"
    return resident


# ---------------------------------------------------------------------------
# Screening
# ---------------------------------------------------------------------------

async def run_screening(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    application: RentalApplication,
) -> ScreeningReport:
    """Request a screening report for an application and persist the result."""
    result = await screening_client.request_screening(
        first_name=application.applicant_first_name,
        last_name=application.applicant_last_name,
        email=application.applicant_email,
        monthly_income=application.monthly_income,
    )
    report = ScreeningReport(
        organization_id=organization_id,
        application_id=application.id,
        provider=result.provider,
        status=result.status,
        recommendation=result.recommendation,
        credit_score=result.credit_score,
        external_ref=result.external_ref,
        report_data=result.report_data,
        requested_at=_now(),
        completed_at=_now() if result.status == "completed" else None,
    )
    db.add(report)
    # Advance the application into screening if it was still fresh.
    if application.status == "submitted":
        application.status = "screening"
    return report


# ---------------------------------------------------------------------------
# Lease e-signing (extends the waiver engine to multi-party lease documents)
# ---------------------------------------------------------------------------

def _gen_token() -> str:
    return secrets.token_hex(32)


async def create_lease_signature_request(
    db: AsyncSession,
    organization_id: uuid.UUID | None,
    *,
    title: str,
    body: str,
    parties: list[dict],
    resident_lease_id: uuid.UUID | None = None,
    created_by_id: uuid.UUID | None = None,
    expires_at: datetime | None = None,
) -> LeaseSignatureRequest:
    """Snapshot + hash a lease document and open a multi-party signing envelope.

    Each ``parties`` entry needs ``signer_name`` and ``signer_email`` and may
    carry ``role`` and ``sign_order``. Merge fields in ``body`` are rendered with
    the organisation context before hashing so the stored document is exactly what
    every party signs.
    """
    if not parties:
        raise FunnelError("A lease signing request needs at least one party.")

    context = waiver_service.build_merge_context(
        recipient_name=None, organization_name=None
    )
    rendered = waiver_service.render_body(body, context)
    doc_hash = waiver_service.compute_document_hash(rendered)

    request = LeaseSignatureRequest(
        organization_id=organization_id,
        resident_lease_id=resident_lease_id,
        title=title,
        rendered_body=rendered,
        document_hash=doc_hash,
        status="sent",
        created_by_id=created_by_id,
        expires_at=expires_at,
        sent_at=_now(),
        parties=[
            LeaseSignatureParty(
                signer_name=p["signer_name"],
                signer_email=waiver_service.normalize_email(p["signer_email"]),
                role=p.get("role", "tenant"),
                sign_order=int(p.get("sign_order", idx)),
                sign_token=_gen_token(),
                status="pending",
            )
            for idx, p in enumerate(parties)
        ],
    )
    db.add(request)
    await db.flush()
    return request


async def load_request_by_token(
    db: AsyncSession, token: str
) -> tuple[LeaseSignatureRequest, LeaseSignatureParty] | None:
    """Resolve a signing party (and its request) from a per-party token."""
    party = (
        await db.execute(
            select(LeaseSignatureParty).where(LeaseSignatureParty.sign_token == token)
        )
    ).scalar_one_or_none()
    if party is None:
        return None
    request = (
        await db.execute(
            select(LeaseSignatureRequest)
            .where(LeaseSignatureRequest.id == party.request_id)
            .options(selectinload(LeaseSignatureRequest.parties))
        )
    ).scalar_one_or_none()
    if request is None:
        return None
    return request, party


def is_expired(request: LeaseSignatureRequest) -> bool:
    if request.expires_at is None:
        return False
    exp = request.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp < _now()


async def sign_party(
    db: AsyncSession,
    request: LeaseSignatureRequest,
    party: LeaseSignatureParty,
    *,
    signature_type: str,
    signature_data: str,
    consent_agreed: bool,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> LeaseSignatureRequest:
    """Record one party's signature and advance the envelope status.

    Enforces ESIGN/UETA controls: explicit consent, attribution, and binding the
    signature to the document hash. The request completes once every party has
    signed.
    """
    if request.status in ("completed", "declined", "voided", "expired"):
        raise FunnelError(f"This lease can no longer be signed (status '{request.status}').")
    if is_expired(request):
        request.status = "expired"
        raise FunnelError("This lease signing request has expired.")
    if party.status == "signed":
        raise FunnelError("This party has already signed.")
    if not consent_agreed:
        raise FunnelError("You must consent to sign electronically.")
    if not signature_data:
        raise FunnelError("A signature is required.")

    party.signature_type = signature_type
    party.signature_data = signature_data
    party.consent_text = waiver_service.ESIGN_CONSENT_TEXT
    party.consent_agreed = True
    party.document_hash = request.document_hash
    party.ip_address = ip_address
    party.user_agent = user_agent
    party.status = "signed"
    party.signed_at = _now()

    signed = sum(1 for p in request.parties if p.status == "signed")
    total = len(request.parties)
    if signed >= total:
        request.status = "completed"
        request.completed_at = _now()
    else:
        request.status = "partially_signed"
    return request


async def decline_party(
    db: AsyncSession,
    request: LeaseSignatureRequest,
    party: LeaseSignatureParty,
) -> LeaseSignatureRequest:
    """Record a party's decline; a single decline voids the whole envelope."""
    if request.status in ("completed", "declined", "voided", "expired"):
        raise FunnelError(f"This lease can no longer be changed (status '{request.status}').")
    party.status = "declined"
    party.declined_at = _now()
    request.status = "declined"
    return request
