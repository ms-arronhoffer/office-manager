"""Portfolio knowledge index + retrieval for the AI assistant (Phase 3).

This generalizes the lease-document semantic search to the whole portfolio. It
builds an organization-scoped index of short text chunks describing maintenance
tickets, leases, and lease abstracts (:class:`~app.models.knowledge_chunk.
KnowledgeChunk`) and answers retrieval queries against both that index *and* the
existing lease-document chunks.

Design mirrors :mod:`app.services.document_search_service`:

* **Embeddings** are computed with Gemini when configured and stored as JSONB.
  Cosine similarity is computed in Python — no ``pgvector`` extension required.
* **Graceful degradation** — when AI is unconfigured (or nothing is embedded
  yet) retrieval falls back to a keyword ``ILIKE`` scan so the feature still
  returns useful context.
* All operations are organization-scoped.

Indexing is best-effort and idempotent: :func:`reindex_organization` replaces an
org's chunks wholesale, so it can be run repeatedly (e.g. from the scheduler or
an explicit admin action) without duplicating rows.
"""
from __future__ import annotations

import logging
import math
import uuid

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.knowledge_chunk import (
    SOURCE_HVAC_CONTRACT,
    SOURCE_INSURANCE_CERTIFICATE,
    SOURCE_LANDLORD,
    SOURCE_LEASE,
    SOURCE_LEASE_ABSTRACT,
    SOURCE_MANAGEMENT_COMPANY,
    SOURCE_OFFICE,
    SOURCE_PORTFOLIO_SUMMARY,
    SOURCE_TICKET,
    SOURCE_TRANSITION,
    SOURCE_VENDOR,
    KnowledgeChunk,
)
from app.models.hvac_contract import HvacContract
from app.models.insurance_certificate import InsuranceCertificate
from app.models.landlord import Landlord
from app.models.lease import Lease
from app.models.lease_abstract import LeaseAbstractClause
from app.models.lease_document_chunk import LeaseDocumentChunk
from app.models.maintenance_ticket import MaintenanceTicket
from app.models.management_company import ManagementCompany
from app.models.office import Office
from app.models.transition import OfficeTransition
from app.models.vendor import Vendor
from app.services import ai_service

logger = logging.getLogger(__name__)

# A knowledge chunk is a compact, self-contained description of one record, so
# it is kept well under the embedding char cap and rarely needs splitting.
MAX_CHUNK_CHARS = 4000
# Bound how many source records of each kind are indexed per org per run.
MAX_RECORDS_PER_KIND = 5000


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


# Common English/question stopwords stripped from keyword queries so meaningful
# terms (e.g. "offices", "total") dominate ranking instead of filler words like
# "how", "many", "in" that match almost every chunk and drown out real signal.
_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "do", "does", "for",
    "from", "has", "have", "how", "i", "in", "is", "it", "its", "list", "many",
    "me", "much", "my", "of", "on", "or", "our", "show", "tell", "that", "the",
    "their", "there", "this", "to", "us", "was", "we", "were", "what", "when",
    "where", "which", "who", "whom", "whose", "why", "with", "you", "your",
})


def _keyword_terms(query: str) -> list[str]:
    """Tokenize ``query`` into lowercased, de-duplicated content terms.

    Strips surrounding punctuation and drops stopwords and 1-character tokens.
    Falls back to the raw lowercased tokens when filtering would leave nothing
    (e.g. a query made entirely of stopwords) so retrieval never returns empty.
    """
    raw = [w.strip(".,!?;:'\"()[]{}").lower() for w in (query or "").split()]
    raw = [w for w in raw if w]
    terms = [w for w in raw if w not in _STOPWORDS and len(w) > 1]
    chosen = terms or raw
    seen: set[str] = set()
    deduped: list[str] = []
    for w in chosen:
        if w not in seen:
            seen.add(w)
            deduped.append(w)
    return deduped


# ── Source → text builders ────────────────────────────────────────────────────

def _ticket_text(ticket: MaintenanceTicket) -> str:
    parts = [
        f"Maintenance ticket: {ticket.subject}",
        f"Status: {ticket.status}",
        f"Priority: {ticket.priority}",
    ]
    category = getattr(ticket, "category", None)
    if category is not None and getattr(category, "name", None):
        parts.append(f"Category: {category.name}")
    vendor = getattr(ticket, "vendor", None)
    if vendor is not None and getattr(vendor, "company_name", None):
        parts.append(f"Assigned vendor: {vendor.company_name}")
    if ticket.description:
        parts.append(f"Description: {ticket.description}")
    if ticket.vendor_completion_notes:
        parts.append(f"Completion notes: {ticket.vendor_completion_notes}")
    return _clean(". ".join(parts))[:MAX_CHUNK_CHARS]


def _lease_text(lease: Lease) -> str:
    parts = [f"Lease: {lease.lease_name}"]
    if lease.lessor_name:
        parts.append(f"Lessor: {lease.lessor_name}")
    if lease.lease_commencement_date:
        parts.append(f"Commencement: {lease.lease_commencement_date}")
    if lease.lease_expiration:
        parts.append(f"Expiration: {lease.lease_expiration}")
    if lease.notice_period:
        parts.append(f"Notice period: {lease.notice_period}")
    if lease.lease_notice_date:
        parts.append(f"Notice date: {lease.lease_notice_date}")
    if lease.payment_amount is not None:
        freq = lease.payment_frequency or "period"
        parts.append(f"Payment: {lease.payment_amount} per {freq}")
    if lease.lease_classification:
        parts.append(f"Classification: {lease.lease_classification}")
    if lease.accounting_standard:
        parts.append(f"Accounting standard: {lease.accounting_standard}")
    return _clean(". ".join(parts))[:MAX_CHUNK_CHARS]


def _abstract_text(clause: LeaseAbstractClause, lease_name: str | None) -> str:
    label = lease_name or "lease"
    parts = [f"Lease abstract clause '{clause.category_key}' for {label}"]
    content = clause.content or {}
    if isinstance(content, dict):
        for key, value in content.items():
            if value in (None, "", [], {}):
                continue
            parts.append(f"{key}: {value}")
    if clause.notes:
        parts.append(f"Notes: {clause.notes}")
    return _clean(". ".join(str(p) for p in parts))[:MAX_CHUNK_CHARS]


def _office_text(office: Office, manager_name: str | None) -> str:
    status = "active" if office.is_active else "inactive"
    parts = [
        f"Office #{office.office_number}: {office.location_name}",
        f"Status: {status}",
    ]
    if office.location_type:
        parts.append(f"Location type: {office.location_type}")
    if manager_name:
        parts.append(f"Office manager: {manager_name}")
    address = ", ".join(
        p for p in [
            office.address_line_1, office.address_line_2,
            office.city, office.state, office.zip_code,
        ] if p
    )
    if address:
        parts.append(f"Address: {address}")
    if office.phone_number:
        parts.append(f"Phone: {office.phone_number}")
    if office.email:
        parts.append(f"Email: {office.email}")
    if office.sector:
        parts.append(f"Sector: {office.sector}")
    if office.total_sqft is not None:
        parts.append(f"Total square feet: {office.total_sqft}")
    if office.usable_sqft is not None:
        parts.append(f"Usable square feet: {office.usable_sqft}")
    if office.current_headcount is not None:
        parts.append(f"Current headcount: {office.current_headcount}")
    if office.headcount_capacity is not None:
        parts.append(f"Headcount capacity: {office.headcount_capacity}")
    if office.notes:
        parts.append(f"Notes: {office.notes}")
    return _clean(". ".join(str(p) for p in parts))[:MAX_CHUNK_CHARS]


def _landlord_text(landlord: Landlord, office_name: str | None) -> str:
    label = landlord.landlord_company or landlord.contact_name or "Landlord"
    parts = [f"Landlord: {label}"]
    if landlord.contact_name:
        parts.append(f"Contact: {landlord.contact_name}")
    if landlord.title:
        parts.append(f"Title: {landlord.title}")
    if landlord.contact_email:
        parts.append(f"Email: {landlord.contact_email}")
    if landlord.contact_phone:
        parts.append(f"Phone: {landlord.contact_phone}")
    if office_name or landlord.office_name:
        parts.append(f"Associated office: {office_name or landlord.office_name}")
    address = ", ".join(
        p for p in [
            landlord.address_line_1, landlord.address_line_2,
            landlord.city, landlord.state, landlord.zip_code,
        ] if p
    ) or landlord.address
    if address:
        parts.append(f"Address: {address}")
    if landlord.management_company:
        parts.append(f"Management company: {landlord.management_company}")
    if landlord.website:
        parts.append(f"Website: {landlord.website}")
    if landlord.notes:
        parts.append(f"Notes: {landlord.notes}")
    return _clean(". ".join(str(p) for p in parts))[:MAX_CHUNK_CHARS]


def _vendor_text(vendor: Vendor) -> str:
    parts = [f"Vendor: {vendor.company_name}"]
    if vendor.services:
        parts.append(f"Services: {vendor.services}")
    if vendor.is_preferred:
        parts.append("Preferred vendor: yes")
    if vendor.contact_name:
        parts.append(f"Contact: {vendor.contact_name}")
    if vendor.contact_email:
        parts.append(f"Email: {vendor.contact_email}")
    if vendor.contact_phone:
        parts.append(f"Phone: {vendor.contact_phone}")
    address = ", ".join(
        p for p in [
            vendor.address_line_1, vendor.address_line_2,
            vendor.city, vendor.state, vendor.zip_code,
        ] if p
    ) or vendor.address
    if address:
        parts.append(f"Address: {address}")
    if vendor.notes:
        parts.append(f"Notes: {vendor.notes}")
    return _clean(". ".join(str(p) for p in parts))[:MAX_CHUNK_CHARS]


def _management_company_text(company: ManagementCompany) -> str:
    parts = [f"Management company: {company.name}"]
    if company.contact_name:
        parts.append(f"Contact: {company.contact_name}")
    if company.contact_title:
        parts.append(f"Title: {company.contact_title}")
    if company.contact_email:
        parts.append(f"Email: {company.contact_email}")
    if company.contact_phone:
        parts.append(f"Phone: {company.contact_phone}")
    address = ", ".join(
        p for p in [
            company.address_line_1, company.address_line_2,
            company.city, company.state, company.zip_code,
        ] if p
    )
    if address:
        parts.append(f"Address: {address}")
    if company.website:
        parts.append(f"Website: {company.website}")
    if company.notes:
        parts.append(f"Notes: {company.notes}")
    return _clean(". ".join(str(p) for p in parts))[:MAX_CHUNK_CHARS]


def _hvac_contract_text(contract: HvacContract, office_name: str | None) -> str:
    label = office_name or contract.office_name or (
        f"office #{contract.office_number}" if contract.office_number else "office"
    )
    parts = [f"HVAC contract for {label}"]
    if contract.hvac_company:
        parts.append(f"HVAC company: {contract.hvac_company}")
    if contract.contact:
        parts.append(f"Contact: {contract.contact}")
    if contract.frequency:
        parts.append(f"Service frequency: {contract.frequency}")
    if contract.comments:
        parts.append(f"Comments: {contract.comments}")
    return _clean(". ".join(str(p) for p in parts))[:MAX_CHUNK_CHARS]


def _transition_text(transition: OfficeTransition, office_name: str | None) -> str:
    label = office_name or (
        f"office #{transition.office_number}" if transition.office_number else "office"
    )
    parts = [
        f"Office transition ({transition.transition_type}) for {label}",
        f"Status: {transition.status}",
    ]
    if transition.address:
        parts.append(f"Current address: {transition.address}")
    if transition.new_address:
        parts.append(f"New address: {transition.new_address}")
    if transition.lease_expiration:
        parts.append(f"Lease expiration: {transition.lease_expiration}")
    if transition.estimated_date:
        parts.append(f"Estimated date: {transition.estimated_date}")
    if transition.notes:
        parts.append(f"Notes: {transition.notes}")
    return _clean(". ".join(str(p) for p in parts))[:MAX_CHUNK_CHARS]


def _insurance_text(
    cert: InsuranceCertificate, holder_label: str | None
) -> str:
    parts = [f"Insurance certificate: {cert.certificate_type}"]
    if holder_label:
        parts.append(f"For: {holder_label}")
    if cert.insurer:
        parts.append(f"Insurer: {cert.insurer}")
    if cert.policy_number:
        parts.append(f"Policy number: {cert.policy_number}")
    if cert.effective_date:
        parts.append(f"Effective: {cert.effective_date}")
    if cert.expiration_date:
        parts.append(f"Expiration: {cert.expiration_date}")
    if cert.limits:
        parts.append(f"Limits: {cert.limits}")
    if cert.certificate_holder:
        parts.append(f"Certificate holder: {cert.certificate_holder}")
    parts.append(f"Verified: {'yes' if cert.is_verified else 'no'}")
    if cert.notes:
        parts.append(f"Notes: {cert.notes}")
    return _clean(". ".join(str(p) for p in parts))[:MAX_CHUNK_CHARS]


# ── Indexing ──────────────────────────────────────────────────────────────────

def _portfolio_summary_text(counts: dict[str, int]) -> str:
    """Build a single rollup chunk of portfolio totals for aggregate questions.

    Retrieval only ever returns a handful of individual record chunks, so a
    question like "how many offices in total?" cannot be answered from them. This
    chunk states the organization-wide counts explicitly and repeats the entity
    words ("offices", "leases", …) so both keyword and semantic retrieval surface
    it for "how many"/"count"/"total" questions.
    """
    parts = [
        "Portfolio summary: organization-wide totals and counts.",
        f"Total offices: {counts['offices']} "
        f"(active offices: {counts['offices_active']}, "
        f"inactive offices: {counts['offices_inactive']}).",
        f"Total leases: {counts['leases']}.",
        f"Total landlords: {counts['landlords']}.",
        f"Total vendors: {counts['vendors']}.",
        f"Total management companies: {counts['management_companies']}.",
        f"Total maintenance tickets: {counts['tickets']} "
        f"(open tickets: {counts['tickets_open']}, "
        f"in-progress tickets: {counts['tickets_in_progress']}, "
        f"closed tickets: {counts['tickets_closed']}).",
        f"Total HVAC contracts: {counts['hvac_contracts']}.",
        f"Total office transitions: {counts['transitions']}.",
        f"Total insurance certificates: {counts['insurance_certificates']}.",
        "Use these totals to answer how many / count / total questions about "
        "offices, leases, landlords, vendors, maintenance tickets, management "
        "companies, HVAC contracts, office transitions, and insurance "
        "certificates across the portfolio.",
    ]
    return _clean(" ".join(parts))[:MAX_CHUNK_CHARS]


async def _collect_chunks(
    db: AsyncSession, organization_id: uuid.UUID
) -> list[dict]:
    """Build (un-embedded) chunk dicts for every indexable record in an org."""
    chunks: list[dict] = []

    tickets = (
        await db.execute(
            select(MaintenanceTicket)
            .options(
                joinedload(MaintenanceTicket.category),
                joinedload(MaintenanceTicket.vendor),
            )
            .where(
                MaintenanceTicket.organization_id == organization_id,
                MaintenanceTicket.is_deleted.is_(False),
            )
            .limit(MAX_RECORDS_PER_KIND)
        )
    ).scalars().all()
    for ticket in tickets:
        chunks.append(
            {
                "source_type": SOURCE_TICKET,
                "source_id": ticket.id,
                "title": f"Ticket: {ticket.subject}",
                "reference": f"maintenance/{ticket.id}",
                "content": _ticket_text(ticket),
            }
        )

    leases = (
        await db.execute(
            select(Lease)
            .where(
                Lease.organization_id == organization_id,
                Lease.is_deleted.is_(False),
            )
            .limit(MAX_RECORDS_PER_KIND)
        )
    ).scalars().all()
    lease_name_by_id = {lease.id: lease.lease_name for lease in leases}
    for lease in leases:
        chunks.append(
            {
                "source_type": SOURCE_LEASE,
                "source_id": lease.id,
                "title": f"Lease: {lease.lease_name}",
                "reference": f"leases/{lease.id}",
                "content": _lease_text(lease),
            }
        )

    clauses = (
        await db.execute(
            select(LeaseAbstractClause)
            .where(LeaseAbstractClause.organization_id == organization_id)
            .limit(MAX_RECORDS_PER_KIND)
        )
    ).scalars().all()
    for clause in clauses:
        lease_name = lease_name_by_id.get(clause.lease_id)
        text = _abstract_text(clause, lease_name)
        title = f"Abstract '{clause.category_key}'"
        if lease_name:
            title = f"{title} — {lease_name}"
        chunks.append(
            {
                "source_type": SOURCE_LEASE_ABSTRACT,
                "source_id": clause.lease_id,
                "title": title,
                "reference": f"leases/{clause.lease_id}",
                "content": text,
            }
        )

    # ── Offices (with their managers) ──────────────────────────────────────
    offices = (
        await db.execute(
            select(Office)
            .options(joinedload(Office.manager))
            .where(
                Office.organization_id == organization_id,
                Office.is_deleted.is_(False),
            )
            .limit(MAX_RECORDS_PER_KIND)
        )
    ).scalars().all()
    office_name_by_id = {o.id: o.location_name for o in offices}
    manager_name_by_id: dict[uuid.UUID, str] = {}
    for office in offices:
        manager = getattr(office, "manager", None)
        manager_name = getattr(manager, "name", None) if manager else None
        if manager is not None and manager_name:
            manager_name_by_id[office.manager_id] = manager_name
        chunks.append(
            {
                "source_type": SOURCE_OFFICE,
                "source_id": office.id,
                "title": f"Office: {office.location_name}",
                "reference": f"offices/{office.id}",
                "content": _office_text(office, manager_name),
            }
        )

    # ── Landlords ──────────────────────────────────────────────────────────
    landlords = (
        await db.execute(
            select(Landlord)
            .where(
                Landlord.organization_id == organization_id,
                Landlord.is_deleted.is_(False),
            )
            .limit(MAX_RECORDS_PER_KIND)
        )
    ).scalars().all()
    for landlord in landlords:
        office_name = office_name_by_id.get(landlord.office_id)
        label = landlord.landlord_company or landlord.contact_name or "Landlord"
        chunks.append(
            {
                "source_type": SOURCE_LANDLORD,
                "source_id": landlord.id,
                "title": f"Landlord: {label}",
                "reference": f"landlords/{landlord.id}",
                "content": _landlord_text(landlord, office_name),
            }
        )

    # ── Vendors ────────────────────────────────────────────────────────────
    vendors = (
        await db.execute(
            select(Vendor)
            .where(
                Vendor.organization_id == organization_id,
                Vendor.is_deleted.is_(False),
            )
            .limit(MAX_RECORDS_PER_KIND)
        )
    ).scalars().all()
    vendor_name_by_id = {v.id: v.company_name for v in vendors}
    for vendor in vendors:
        chunks.append(
            {
                "source_type": SOURCE_VENDOR,
                "source_id": vendor.id,
                "title": f"Vendor: {vendor.company_name}",
                "reference": f"vendors/{vendor.id}",
                "content": _vendor_text(vendor),
            }
        )

    # ── Management companies ───────────────────────────────────────────────
    companies = (
        await db.execute(
            select(ManagementCompany)
            .where(
                ManagementCompany.organization_id == organization_id,
                ManagementCompany.is_deleted.is_(False),
            )
            .limit(MAX_RECORDS_PER_KIND)
        )
    ).scalars().all()
    for company in companies:
        chunks.append(
            {
                "source_type": SOURCE_MANAGEMENT_COMPANY,
                "source_id": company.id,
                "title": f"Management company: {company.name}",
                "reference": f"management-companies/{company.id}",
                "content": _management_company_text(company),
            }
        )

    # ── HVAC contracts ─────────────────────────────────────────────────────
    contracts = (
        await db.execute(
            select(HvacContract)
            .where(
                HvacContract.organization_id == organization_id,
                HvacContract.is_deleted.is_(False),
            )
            .limit(MAX_RECORDS_PER_KIND)
        )
    ).scalars().all()
    for contract in contracts:
        office_name = office_name_by_id.get(contract.office_id)
        label = office_name or contract.office_name or "office"
        chunks.append(
            {
                "source_type": SOURCE_HVAC_CONTRACT,
                "source_id": contract.id,
                "title": f"HVAC contract — {label}",
                "reference": f"hvac-contracts/{contract.id}",
                "content": _hvac_contract_text(contract, office_name),
            }
        )

    # ── Office transitions ─────────────────────────────────────────────────
    transitions = (
        await db.execute(
            select(OfficeTransition)
            .where(
                OfficeTransition.organization_id == organization_id,
                OfficeTransition.is_deleted.is_(False),
            )
            .limit(MAX_RECORDS_PER_KIND)
        )
    ).scalars().all()
    for transition in transitions:
        office_name = office_name_by_id.get(transition.office_id)
        label = office_name or (
            f"office #{transition.office_number}"
            if transition.office_number else "office"
        )
        chunks.append(
            {
                "source_type": SOURCE_TRANSITION,
                "source_id": transition.id,
                "title": f"Transition ({transition.transition_type}) — {label}",
                "reference": f"transitions/{transition.id}",
                "content": _transition_text(transition, office_name),
            }
        )

    # ── Insurance certificates ─────────────────────────────────────────────
    certificates = (
        await db.execute(
            select(InsuranceCertificate)
            .where(InsuranceCertificate.organization_id == organization_id)
            .limit(MAX_RECORDS_PER_KIND)
        )
    ).scalars().all()
    for cert in certificates:
        holder_label = (
            vendor_name_by_id.get(cert.vendor_id)
            if cert.vendor_id else None
        )
        chunks.append(
            {
                "source_type": SOURCE_INSURANCE_CERTIFICATE,
                "source_id": cert.id,
                "title": f"Insurance certificate: {cert.certificate_type}",
                "reference": f"insurance/{cert.id}",
                "content": _insurance_text(cert, holder_label),
            }
        )

    # ── Portfolio summary (organization-level rollup of totals) ────────────
    # Prepended so aggregate "how many"/"count" questions are answerable even
    # though retrieval only returns a few individual record chunks.
    summary_counts = {
        "offices": len(offices),
        "offices_active": sum(1 for o in offices if o.is_active),
        "offices_inactive": sum(1 for o in offices if not o.is_active),
        "leases": len(leases),
        "landlords": len(landlords),
        "vendors": len(vendors),
        "management_companies": len(companies),
        "tickets": len(tickets),
        "tickets_open": sum(1 for t in tickets if t.status == "open"),
        "tickets_in_progress": sum(1 for t in tickets if t.status == "in_progress"),
        "tickets_closed": sum(
            1 for t in tickets if t.status in ("closed", "completed")
        ),
        "hvac_contracts": len(contracts),
        "transitions": len(transitions),
        "insurance_certificates": len(certificates),
    }
    chunks.insert(
        0,
        {
            "source_type": SOURCE_PORTFOLIO_SUMMARY,
            "source_id": organization_id,
            "title": "Portfolio summary (totals)",
            "reference": "dashboard",
            "content": _portfolio_summary_text(summary_counts),
        },
    )

    # Drop empty-content chunks (nothing useful to embed or match).
    return [c for c in chunks if c["content"]]


async def reindex_organization(
    db: AsyncSession, organization_id: uuid.UUID
) -> int:
    """Rebuild the knowledge index for one organization. Returns chunk count.

    Idempotent: deletes the org's existing chunks and re-inserts a fresh set.
    Embeddings are added when Gemini is configured; otherwise chunks are stored
    keyword-only so retrieval still works.
    """
    chunks = await _collect_chunks(db, organization_id)

    embeddings: list[list[float]] | None = None
    if chunks and ai_service.is_configured():
        try:
            embeddings = await ai_service.embed_texts([c["content"] for c in chunks])
        except ai_service.AIError as exc:
            logger.warning(
                "Knowledge embedding failed for org %s; storing keyword-only: %s",
                organization_id,
                exc,
            )
            embeddings = None

    await db.execute(
        delete(KnowledgeChunk).where(
            KnowledgeChunk.organization_id == organization_id
        )
    )
    for idx, chunk in enumerate(chunks):
        db.add(
            KnowledgeChunk(
                organization_id=organization_id,
                source_type=chunk["source_type"],
                source_id=chunk["source_id"],
                title=chunk["title"][:500],
                reference=chunk["reference"],
                chunk_index=0,
                content=chunk["content"],
                embedding=embeddings[idx] if embeddings else None,
            )
        )
    await db.commit()
    return len(chunks)


# ── Retrieval ─────────────────────────────────────────────────────────────────

def _normalize_knowledge(score: float, chunk: KnowledgeChunk, mode: str) -> dict:
    return {
        "source_type": chunk.source_type,
        "source_id": str(chunk.source_id),
        "title": chunk.title,
        "reference": chunk.reference,
        "content": chunk.content,
        "score": round(float(score), 4),
        "match_type": mode,
    }


def _normalize_document(
    score: float, chunk: LeaseDocumentChunk, lease_name: str | None, mode: str
) -> dict:
    label = chunk.source_filename or "document"
    if lease_name:
        label = f"{label} — {lease_name}"
    return {
        "source_type": "lease_document",
        "source_id": str(chunk.lease_id),
        "title": label,
        "reference": f"leases/{chunk.lease_id}",
        "content": chunk.content,
        "score": round(float(score), 4),
        "match_type": mode,
    }


async def retrieve(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    query: str,
    limit: int = 8,
) -> list[dict]:
    """Return the most relevant portfolio chunks for ``query`` (org-scoped).

    Combines the generalized knowledge index with the existing lease-document
    chunks. Uses semantic (embedding) ranking when AI is configured and embedded
    chunks exist; otherwise falls back to a keyword ``ILIKE`` scan.
    """
    query = (query or "").strip()
    if not query:
        return []

    query_embedding: list[float] | None = None
    if ai_service.is_configured():
        try:
            vectors = await ai_service.embed_texts([query])
            query_embedding = vectors[0] if vectors else None
        except ai_service.AIError as exc:
            logger.info("Query embedding unavailable, using keyword search: %s", exc)
            query_embedding = None

    if query_embedding is not None:
        results = await _semantic_retrieve(
            db, organization_id=organization_id, query_embedding=query_embedding, limit=limit
        )
        if results:
            return results
        # Fall through to keyword search when nothing is embedded yet.

    return await _keyword_retrieve(
        db, organization_id=organization_id, query=query, limit=limit
    )


async def _lease_names(db: AsyncSession, lease_ids: set[uuid.UUID]) -> dict:
    if not lease_ids:
        return {}
    leases = (
        await db.execute(select(Lease).where(Lease.id.in_(lease_ids)))
    ).scalars().all()
    return {lease.id: lease.lease_name for lease in leases}


async def _semantic_retrieve(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    query_embedding: list[float],
    limit: int,
) -> list[dict]:
    scored: list[tuple[float, str, object]] = []

    k_chunks = (
        await db.execute(
            select(KnowledgeChunk).where(
                KnowledgeChunk.organization_id == organization_id,
                KnowledgeChunk.embedding.isnot(None),
            )
        )
    ).scalars().all()
    for chunk in k_chunks:
        scored.append((_cosine(query_embedding, chunk.embedding or []), "knowledge", chunk))

    d_chunks = (
        await db.execute(
            select(LeaseDocumentChunk).where(
                LeaseDocumentChunk.organization_id == organization_id,
                LeaseDocumentChunk.embedding.isnot(None),
            )
        )
    ).scalars().all()
    for chunk in d_chunks:
        scored.append((_cosine(query_embedding, chunk.embedding or []), "document", chunk))

    if not scored:
        return []
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:limit]
    return await _hydrate(db, top, mode="semantic")


async def _keyword_retrieve(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    query: str,
    limit: int,
) -> list[dict]:
    words = _keyword_terms(query)
    terms = words or [query.lower()]

    def keyword_score(content: str) -> int:
        lowered = (content or "").lower()
        return sum(lowered.count(t) for t in terms)

    scored: list[tuple[float, str, object]] = []

    k_filters = [KnowledgeChunk.content.ilike(f"%{w}%") for w in terms]
    k_chunks = (
        await db.execute(
            select(KnowledgeChunk)
            .where(
                KnowledgeChunk.organization_id == organization_id,
                or_(*k_filters),
            )
            .limit(limit * 10)
        )
    ).scalars().all()
    for chunk in k_chunks:
        scored.append((keyword_score(chunk.content), "knowledge", chunk))

    d_filters = [LeaseDocumentChunk.content.ilike(f"%{w}%") for w in terms]
    d_chunks = (
        await db.execute(
            select(LeaseDocumentChunk)
            .where(
                LeaseDocumentChunk.organization_id == organization_id,
                or_(*d_filters),
            )
            .limit(limit * 10)
        )
    ).scalars().all()
    for chunk in d_chunks:
        scored.append((keyword_score(chunk.content), "document", chunk))

    scored = [s for s in scored if s[0] > 0]
    if not scored:
        return []
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:limit]
    return await _hydrate(db, top, mode="keyword")


async def _hydrate(
    db: AsyncSession, top: list[tuple[float, str, object]], *, mode: str
) -> list[dict]:
    doc_lease_ids = {
        chunk.lease_id for _, kind, chunk in top if kind == "document"
    }
    lease_names = await _lease_names(db, doc_lease_ids)

    results: list[dict] = []
    for score, kind, chunk in top:
        if kind == "knowledge":
            results.append(_normalize_knowledge(score, chunk, mode))
        else:
            results.append(
                _normalize_document(score, chunk, lease_names.get(chunk.lease_id), mode)
            )
    return results
