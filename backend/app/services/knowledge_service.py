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

import json
import logging
import math
import uuid

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.base import Base
# Importing the models package ensures *every* mapped model is registered on
# ``Base.registry`` so the generic catch-all indexer below can discover any
# organization-scoped table, not just the ones explicitly imported here.
import app.models  # noqa: F401

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
    SOURCE_RENTAL_UNIT,
    SOURCE_RESIDENT,
    SOURCE_RESIDENT_LEASE,
    SOURCE_RENT_CHARGE,
    SOURCE_OWNER,
    SOURCE_OWNER_DISTRIBUTION,
    SOURCE_VENDOR_BILL,
    SOURCE_CUSTOMER_INVOICE,
    SOURCE_BANK_ACCOUNT,
    SOURCE_BUDGET,
    SOURCE_INSPECTION,
    SOURCE_LISTING,
    SOURCE_RENTAL_APPLICATION,
    SOURCE_SCREENING_REPORT,
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
from app.models.resident import RentalUnit, Resident, ResidentLease
from app.models.rent import RentCharge
from app.models.owner import PropertyOwner, OwnerDistribution
from app.models.vendor_bill import VendorBill
from app.models.customer_invoice import CustomerInvoice
from app.models.bank_account import BankAccount
from app.models.budget import Budget
from app.models.inspection import Inspection
from app.models.listing import VacancyListing
from app.models.leasing_funnel import RentalApplication, ScreeningReport
from app.services import ai_service

logger = logging.getLogger(__name__)

# A knowledge chunk is a compact, self-contained description of one record, so
# it is kept well under the embedding char cap and rarely needs splitting.
MAX_CHUNK_CHARS = 4000
# Bound how many source records of each kind are indexed per org per run.
MAX_RECORDS_PER_KIND = 5000

# ── Semantic ranking quality knobs ────────────────────────────────────────────
# Cosine similarities below this absolute floor are treated as noise and dropped
# so clearly-irrelevant chunks never pollute the model's context. The top match
# is always kept regardless, so a thin-but-real result set is never emptied.
SEMANTIC_RELEVANCE_FLOOR = 0.15
# A chunk is also dropped when it scores far below the best match for the query
# (best * this ratio), which keeps a long tail of weak, loosely-related chunks
# out of the prompt even when their absolute score clears the floor.
SEMANTIC_RELATIVE_FLOOR_RATIO = 0.6
# Cap how many chunks may come from a single source record so one verbose lease
# or document cannot crowd out coverage of other relevant records (diversity).
MAX_CHUNKS_PER_SOURCE = 3


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


# ── Generic catch-all indexing ────────────────────────────────────────────────
# The builders below produce hand-tuned, richly-labelled text for the core
# entities. Everything else that is organization-scoped is picked up generically
# by reflecting over its columns (see ``_collect_generic_chunks``) so the
# assistant can answer questions about *any* data in the database, not only the
# entities with a bespoke builder.

# Tables already covered by a bespoke builder above — skipped by the generic
# indexer to avoid duplicate chunks.
_BESPOKE_TABLES = frozenset({
    "maintenance_tickets", "leases", "lease_abstract_clauses", "offices",
    "landlords", "vendors", "management_companies", "hvac_contracts",
    "office_transitions", "insurance_certificates", "rental_units", "residents",
    "resident_leases", "rent_charges", "property_owners", "owner_distributions",
    "vendor_bills", "customer_invoices", "bank_accounts", "budgets",
    "inspections", "vacancy_listings", "rental_applications", "screening_reports",
})

# Tables the generic indexer must never touch: the embedding indexes themselves,
# credential/secret stores, and low-signal internal metering/billing/audit noise.
# Indexing these would either leak secrets into the assistant's context or bloat
# the index with rows that carry no answerable business meaning.
_GENERIC_SKIP_TABLES = frozenset({
    "knowledge_chunks", "lease_document_chunks",
    "users", "api_keys", "client_portal_accounts", "webhooks",
    "impersonation_sessions", "auth_lockouts", "site_settings",
    "usage_events", "activity_log", "email_log",
    "billing_charges", "billing_credits", "billing_invoices",
    "billing_refunds", "billing_subscriptions", "billing_coupons",
})

# Column-name fragments whose values must never be embedded or returned.
_SENSITIVE_COLUMN_FRAGMENTS = (
    "password", "secret", "token", "hash", "api_key", "apikey",
    "private_key", "signature", "ssn", "salt",
)

# Structural columns that carry no natural-language signal.
_GENERIC_SKIP_COLUMNS = frozenset({
    "id", "organization_id", "is_deleted", "deleted_at", "embedding",
    "search_vector", "created_at", "updated_at",
})

# Columns (in priority order) used to derive a human-readable record label.
_LABEL_COLUMNS = (
    "name", "title", "subject", "label", "display_name", "code",
    "number", "reference",
)

# Bound how many rows and how much text the generic indexer emits per table.
_GENERIC_MAX_RECORDS_PER_TABLE = 2000
_GENERIC_VALUE_MAXLEN = 500

# Cached discovery result; computed once per process from the ORM registry.
_GENERIC_MODELS_CACHE: list[tuple[type, object, str]] | None = None


def _humanize(name: str) -> str:
    """Turn a snake_case column/table name into a display label."""
    return name.replace("_", " ").strip().capitalize()


def _is_sensitive_column(name: str) -> bool:
    lowered = name.lower()
    return any(frag in lowered for frag in _SENSITIVE_COLUMN_FRAGMENTS)


def _generic_indexable_models() -> list[tuple[type, object, str]]:
    """Discover every organization-scoped model without a bespoke builder.

    Returns ``(class, mapper, tablename)`` tuples for models that (a) carry an
    ``organization_id`` column, (b) have a single UUID ``id`` primary key (so the
    row fits :class:`KnowledgeChunk.source_id`), and (c) are neither already
    covered by a hand-tuned builder nor on the sensitive/low-signal skip list.
    The result is cached and sorted by table name for deterministic output.
    """
    global _GENERIC_MODELS_CACHE
    if _GENERIC_MODELS_CACHE is not None:
        return _GENERIC_MODELS_CACHE

    discovered: list[tuple[type, object, str]] = []
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        table = getattr(cls, "__tablename__", None)
        if not table or table in _BESPOKE_TABLES or table in _GENERIC_SKIP_TABLES:
            continue
        column_keys = {col.key for col in mapper.columns}
        if "organization_id" not in column_keys:
            continue
        primary_key = list(mapper.primary_key)
        if len(primary_key) != 1 or primary_key[0].key != "id":
            continue
        discovered.append((cls, mapper, table))

    discovered.sort(key=lambda item: item[2])
    _GENERIC_MODELS_CACHE = discovered
    return discovered


def _format_generic_value(value) -> str | None:
    """Render a column value as compact text, or ``None`` to skip it."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, uuid.UUID):
        # Opaque identifiers add noise without answerable meaning.
        return None
    if isinstance(value, (list, dict)):
        try:
            text = json.dumps(value, default=str, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(value)
    else:
        text = str(value)
    text = _clean(text)
    if not text:
        return None
    if len(text) > _GENERIC_VALUE_MAXLEN:
        text = text[:_GENERIC_VALUE_MAXLEN] + "…"
    return text


def _generic_record_text(instance, mapper) -> str:
    """Build a labelled ``Field: value`` description from a record's columns.

    Foreign-key/opaque id columns, structural bookkeeping columns, and sensitive
    columns (passwords, tokens, hashes, …) are omitted.
    """
    parts: list[str] = []
    for col in mapper.columns:
        key = col.key
        if key in _GENERIC_SKIP_COLUMNS or key.endswith("_id"):
            continue
        if _is_sensitive_column(key):
            continue
        formatted = _format_generic_value(getattr(instance, key, None))
        if formatted is None:
            continue
        parts.append(f"{_humanize(key)}: {formatted}")
    return _clean("\n".join(parts))[:MAX_CHUNK_CHARS] if parts else ""


def _generic_record_title(instance, mapper, table: str) -> str:
    human = _humanize(table)
    column_keys = mapper.columns.keys()
    for col in _LABEL_COLUMNS:
        if col in column_keys:
            value = getattr(instance, col, None)
            if value not in (None, ""):
                return f"{human}: {_clean(str(value))[:120]}"
    return human


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


# ── Newer domains (residential + accounting) text builders ────────────────────

def _resident_name(resident: Resident) -> str:
    name = " ".join(p for p in (resident.first_name, resident.last_name) if p).strip()
    return name or resident.email or "Resident"


def _rental_unit_text(unit: RentalUnit, office_name: str | None) -> str:
    label = unit.name or unit.unit_number or "Rental unit"
    parts = [f"Rental unit: {label}"]
    if unit.unit_number:
        parts.append(f"Unit number: {unit.unit_number}")
    if office_name:
        parts.append(f"Property/office: {office_name}")
    address = ", ".join(
        p for p in (
            unit.address_line_1, unit.address_line_2, unit.city, unit.state, unit.zip_code
        ) if p
    )
    if address:
        parts.append(f"Address: {address}")
    if unit.property_type:
        parts.append(f"Type: {unit.property_type}")
    if unit.bedrooms is not None:
        parts.append(f"Bedrooms: {unit.bedrooms}")
    if unit.bathrooms is not None:
        parts.append(f"Bathrooms: {unit.bathrooms}")
    if unit.square_feet is not None:
        parts.append(f"Square feet: {unit.square_feet}")
    if unit.market_rent is not None:
        parts.append(f"Market rent: {unit.market_rent}")
    if unit.status:
        parts.append(f"Status: {unit.status}")
    return _clean(". ".join(str(p) for p in parts))[:MAX_CHUNK_CHARS]


def _resident_text(resident: Resident) -> str:
    parts = [f"Resident: {_resident_name(resident)}"]
    if resident.email:
        parts.append(f"Email: {resident.email}")
    if resident.phone:
        parts.append(f"Phone: {resident.phone}")
    if resident.company:
        parts.append(f"Company: {resident.company}")
    if resident.status:
        parts.append(f"Status: {resident.status}")
    address = ", ".join(
        p for p in (
            resident.address_line_1, resident.city, resident.state, resident.zip_code
        ) if p
    )
    if address:
        parts.append(f"Address: {address}")
    return _clean(". ".join(str(p) for p in parts))[:MAX_CHUNK_CHARS]


def _resident_lease_text(lease: ResidentLease, unit_label: str | None) -> str:
    parts = [f"Resident lease: {lease.name or 'Lease'}"]
    if unit_label:
        parts.append(f"Unit: {unit_label}")
    if lease.status:
        parts.append(f"Status: {lease.status}")
    if lease.start_date:
        parts.append(f"Start: {lease.start_date}")
    if lease.end_date:
        parts.append(f"End: {lease.end_date}")
    if lease.rent_amount is not None:
        freq = lease.rent_frequency or "monthly"
        parts.append(f"Rent: {lease.rent_amount} ({freq})")
    if lease.security_deposit is not None:
        parts.append(f"Security deposit: {lease.security_deposit}")
    if lease.move_in_date:
        parts.append(f"Move-in: {lease.move_in_date}")
    if lease.move_out_date:
        parts.append(f"Move-out: {lease.move_out_date}")
    return _clean(". ".join(str(p) for p in parts))[:MAX_CHUNK_CHARS]


def _rent_charge_text(charge: RentCharge, unit_label: str | None) -> str:
    parts = [f"Rent charge: {charge.charge_type or 'rent'}"]
    if charge.description:
        parts.append(f"Description: {charge.description}")
    if unit_label:
        parts.append(f"Unit: {unit_label}")
    if charge.amount is not None:
        freq = charge.frequency or "monthly"
        parts.append(f"Amount: {charge.amount} ({freq})")
    if charge.day_of_month is not None:
        parts.append(f"Billed day of month: {charge.day_of_month}")
    if charge.start_date:
        parts.append(f"Start: {charge.start_date}")
    if charge.end_date:
        parts.append(f"End: {charge.end_date}")
    parts.append(f"Active: {'yes' if charge.active else 'no'}")
    return _clean(". ".join(str(p) for p in parts))[:MAX_CHUNK_CHARS]


def _owner_text(owner: PropertyOwner) -> str:
    label = owner.name or " ".join(
        p for p in (owner.first_name, owner.last_name) if p
    ).strip() or "Owner"
    parts = [f"Property owner: {label}"]
    if owner.owner_type:
        parts.append(f"Type: {owner.owner_type}")
    if owner.email:
        parts.append(f"Email: {owner.email}")
    if owner.phone:
        parts.append(f"Phone: {owner.phone}")
    if owner.management_fee_percent is not None:
        parts.append(f"Management fee percent: {owner.management_fee_percent}")
    if owner.status:
        parts.append(f"Status: {owner.status}")
    return _clean(". ".join(str(p) for p in parts))[:MAX_CHUNK_CHARS]


def _owner_distribution_text(dist: OwnerDistribution, owner_label: str | None) -> str:
    parts = ["Owner distribution"]
    if owner_label:
        parts.append(f"Owner: {owner_label}")
    if dist.distribution_date:
        parts.append(f"Date: {dist.distribution_date}")
    if dist.amount is not None:
        parts.append(f"Amount: {dist.amount}")
    if dist.method:
        parts.append(f"Method: {dist.method}")
    if dist.status:
        parts.append(f"Status: {dist.status}")
    if dist.reference:
        parts.append(f"Reference: {dist.reference}")
    return _clean(". ".join(str(p) for p in parts))[:MAX_CHUNK_CHARS]


def _vendor_bill_text(bill: VendorBill, vendor_name: str | None) -> str:
    parts = [f"Vendor bill {bill.bill_number or ''}".strip()]
    if vendor_name:
        parts.append(f"Vendor: {vendor_name}")
    if bill.bill_date:
        parts.append(f"Bill date: {bill.bill_date}")
    if bill.due_date:
        parts.append(f"Due date: {bill.due_date}")
    if bill.total_amount is not None:
        parts.append(f"Total: {bill.total_amount}")
    if bill.status:
        parts.append(f"Status: {bill.status}")
    if bill.memo:
        parts.append(f"Memo: {bill.memo}")
    return _clean(". ".join(str(p) for p in parts))[:MAX_CHUNK_CHARS]


def _customer_invoice_text(invoice: CustomerInvoice, customer_name: str | None) -> str:
    parts = [f"Customer invoice {invoice.invoice_number or ''}".strip()]
    if customer_name:
        parts.append(f"Customer: {customer_name}")
    if invoice.invoice_date:
        parts.append(f"Invoice date: {invoice.invoice_date}")
    if invoice.due_date:
        parts.append(f"Due date: {invoice.due_date}")
    if invoice.total_amount is not None:
        parts.append(f"Total: {invoice.total_amount}")
    if invoice.status:
        parts.append(f"Status: {invoice.status}")
    if invoice.source:
        parts.append(f"Source: {invoice.source}")
    if invoice.memo:
        parts.append(f"Memo: {invoice.memo}")
    return _clean(". ".join(str(p) for p in parts))[:MAX_CHUNK_CHARS]


def _bank_account_text(account: BankAccount) -> str:
    parts = [f"Bank account: {account.name}"]
    if account.institution:
        parts.append(f"Institution: {account.institution}")
    if account.account_number_last4:
        parts.append(f"Account ending: {account.account_number_last4}")
    parts.append(f"Active: {'yes' if account.is_active else 'no'}")
    if account.notes:
        parts.append(f"Notes: {account.notes}")
    return _clean(". ".join(str(p) for p in parts))[:MAX_CHUNK_CHARS]


def _budget_text(budget: Budget) -> str:
    parts = [f"Budget: {budget.name}"]
    if budget.fiscal_year is not None:
        parts.append(f"Fiscal year: {budget.fiscal_year}")
    if budget.status:
        parts.append(f"Status: {budget.status}")
    if budget.notes:
        parts.append(f"Notes: {budget.notes}")
    return _clean(". ".join(str(p) for p in parts))[:MAX_CHUNK_CHARS]


def _inspection_text(inspection: Inspection, office_name: str | None) -> str:
    parts = [f"Inspection: {inspection.title}"]
    if office_name:
        parts.append(f"Office: {office_name}")
    if inspection.status:
        parts.append(f"Status: {inspection.status}")
    if inspection.scheduled_date:
        parts.append(f"Scheduled: {inspection.scheduled_date}")
    if inspection.overall_result:
        parts.append(f"Result: {inspection.overall_result}")
    if inspection.notes:
        parts.append(f"Notes: {inspection.notes}")
    return _clean(". ".join(str(p) for p in parts))[:MAX_CHUNK_CHARS]


def _listing_text(listing: VacancyListing, unit_label: str | None) -> str:
    parts = [f"Vacancy listing: {listing.title}"]
    if listing.headline:
        parts.append(f"Headline: {listing.headline}")
    if unit_label:
        parts.append(f"Unit: {unit_label}")
    if listing.marketing_rent is not None:
        parts.append(f"Marketing rent: {listing.marketing_rent}")
    if listing.available_date:
        parts.append(f"Available: {listing.available_date}")
    if listing.status:
        parts.append(f"Status: {listing.status}")
    if listing.description:
        parts.append(f"Description: {listing.description}")
    return _clean(". ".join(str(p) for p in parts))[:MAX_CHUNK_CHARS]


def _application_name(app: RentalApplication) -> str:
    name = " ".join(
        p for p in (app.applicant_first_name, app.applicant_last_name) if p
    ).strip()
    return name or app.applicant_email or "Applicant"


def _rental_application_text(
    app: RentalApplication, unit_label: str | None
) -> str:
    parts = [f"Rental application: {_application_name(app)}"]
    if app.applicant_email:
        parts.append(f"Email: {app.applicant_email}")
    if app.applicant_phone:
        parts.append(f"Phone: {app.applicant_phone}")
    if unit_label:
        parts.append(f"Unit: {unit_label}")
    if app.status:
        parts.append(f"Status: {app.status}")
    if app.desired_move_in:
        parts.append(f"Desired move-in: {app.desired_move_in}")
    if app.monthly_income is not None:
        parts.append(f"Monthly income: {app.monthly_income}")
    if app.decision_notes:
        parts.append(f"Decision notes: {app.decision_notes}")
    if app.notes:
        parts.append(f"Notes: {app.notes}")
    return _clean(". ".join(str(p) for p in parts))[:MAX_CHUNK_CHARS]


def _screening_report_text(
    report: ScreeningReport, applicant_label: str | None
) -> str:
    parts = ["Tenant screening report"]
    if applicant_label:
        parts.append(f"Applicant: {applicant_label}")
    if report.provider:
        parts.append(f"Provider: {report.provider}")
    if report.status:
        parts.append(f"Status: {report.status}")
    if report.recommendation:
        parts.append(f"Recommendation: {report.recommendation}")
    if report.credit_score is not None:
        parts.append(f"Credit score: {report.credit_score}")
    if report.completed_at:
        parts.append(f"Completed: {report.completed_at}")
    return _clean(". ".join(str(p) for p in parts))[:MAX_CHUNK_CHARS]


# ── Indexing ──────────────────────────────────────────────────────────────────

def _portfolio_summary_text(
    counts: dict[str, int], generic_counts: dict[str, int] | None = None
) -> str:
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
        f"Total rental units: {counts['rental_units']}.",
        f"Total residents: {counts['residents']}.",
        f"Total resident leases: {counts['resident_leases']}.",
        f"Total rent charges: {counts['rent_charges']}.",
        f"Total property owners: {counts['owners']}.",
        f"Total owner distributions: {counts['owner_distributions']}.",
        f"Total vendor bills (accounts payable): {counts['vendor_bills']}.",
        f"Total customer invoices (accounts receivable): {counts['customer_invoices']}.",
        f"Total bank accounts: {counts['bank_accounts']}.",
        f"Total budgets: {counts['budgets']}.",
        f"Total inspections: {counts['inspections']}.",
        f"Total vacancy listings: {counts['listings']}.",
        f"Total rental applications: {counts['applications']} "
        f"(applications in screening: {counts['applications_screening']}).",
        f"Total tenant screening reports: {counts['screening_reports']}.",
        "Use these totals to answer how many / count / total questions about "
        "offices, leases, landlords, vendors, maintenance tickets, management "
        "companies, HVAC contracts, office transitions, insurance certificates, "
        "rental units, residents, resident leases, rent charges, property "
        "owners, owner distributions, vendor bills, customer invoices, bank "
        "accounts, budgets, inspections, vacancy listings, rental applications, "
        "and tenant screening reports across the portfolio.",
    ]
    # Fold in counts for every other organization-scoped table picked up by the
    # generic indexer so "how many <anything>" questions are answerable too.
    for table in sorted(generic_counts or {}):
        parts.append(f"Total {table.replace('_', ' ')}: {generic_counts[table]}.")
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

    # ── Rental units (org-as-lessor) ───────────────────────────────────────
    units = (
        await db.execute(
            select(RentalUnit)
            .where(
                RentalUnit.organization_id == organization_id,
                RentalUnit.is_deleted.is_(False),
            )
            .limit(MAX_RECORDS_PER_KIND)
        )
    ).scalars().all()
    unit_label_by_id: dict[uuid.UUID, str] = {}
    for unit in units:
        label = unit.name or unit.unit_number or "Rental unit"
        unit_label_by_id[unit.id] = label
        office_name = office_name_by_id.get(unit.office_id)
        chunks.append(
            {
                "source_type": SOURCE_RENTAL_UNIT,
                "source_id": unit.id,
                "title": f"Rental unit: {label}",
                "reference": "residential/residents",
                "content": _rental_unit_text(unit, office_name),
            }
        )

    # ── Residents ──────────────────────────────────────────────────────────
    residents = (
        await db.execute(
            select(Resident)
            .where(
                Resident.organization_id == organization_id,
                Resident.is_deleted.is_(False),
            )
            .limit(MAX_RECORDS_PER_KIND)
        )
    ).scalars().all()
    for resident in residents:
        chunks.append(
            {
                "source_type": SOURCE_RESIDENT,
                "source_id": resident.id,
                "title": f"Resident: {_resident_name(resident)}",
                "reference": "residential/residents",
                "content": _resident_text(resident),
            }
        )

    # ── Resident leases ────────────────────────────────────────────────────
    resident_leases = (
        await db.execute(
            select(ResidentLease)
            .where(
                ResidentLease.organization_id == organization_id,
                ResidentLease.is_deleted.is_(False),
            )
            .limit(MAX_RECORDS_PER_KIND)
        )
    ).scalars().all()
    for rlease in resident_leases:
        unit_label = unit_label_by_id.get(rlease.unit_id)
        chunks.append(
            {
                "source_type": SOURCE_RESIDENT_LEASE,
                "source_id": rlease.id,
                "title": f"Resident lease: {rlease.name or 'Lease'}",
                "reference": "residential/leases",
                "content": _resident_lease_text(rlease, unit_label),
            }
        )

    # ── Rent charges ───────────────────────────────────────────────────────
    rent_charges = (
        await db.execute(
            select(RentCharge)
            .where(
                RentCharge.organization_id == organization_id,
                RentCharge.is_deleted.is_(False),
            )
            .limit(MAX_RECORDS_PER_KIND)
        )
    ).scalars().all()
    lease_unit_label: dict[uuid.UUID, str] = {}
    for rlease in resident_leases:
        label = unit_label_by_id.get(rlease.unit_id)
        if label:
            lease_unit_label[rlease.id] = label
    for charge in rent_charges:
        unit_label = lease_unit_label.get(charge.resident_lease_id)
        chunks.append(
            {
                "source_type": SOURCE_RENT_CHARGE,
                "source_id": charge.id,
                "title": f"Rent charge: {charge.charge_type or 'rent'}",
                "reference": "residential/rent",
                "content": _rent_charge_text(charge, unit_label),
            }
        )

    # ── Property owners ────────────────────────────────────────────────────
    owners = (
        await db.execute(
            select(PropertyOwner)
            .where(
                PropertyOwner.organization_id == organization_id,
                PropertyOwner.is_deleted.is_(False),
            )
            .limit(MAX_RECORDS_PER_KIND)
        )
    ).scalars().all()
    owner_label_by_id: dict[uuid.UUID, str] = {}
    for owner in owners:
        label = owner.name or " ".join(
            p for p in (owner.first_name, owner.last_name) if p
        ).strip() or "Owner"
        owner_label_by_id[owner.id] = label
        chunks.append(
            {
                "source_type": SOURCE_OWNER,
                "source_id": owner.id,
                "title": f"Property owner: {label}",
                "reference": "residential/owners",
                "content": _owner_text(owner),
            }
        )

    # ── Owner distributions ────────────────────────────────────────────────
    distributions = (
        await db.execute(
            select(OwnerDistribution)
            .where(OwnerDistribution.organization_id == organization_id)
            .limit(MAX_RECORDS_PER_KIND)
        )
    ).scalars().all()
    for dist in distributions:
        owner_label = owner_label_by_id.get(dist.owner_id)
        chunks.append(
            {
                "source_type": SOURCE_OWNER_DISTRIBUTION,
                "source_id": dist.id,
                "title": "Owner distribution",
                "reference": "residential/owners",
                "content": _owner_distribution_text(dist, owner_label),
            }
        )

    # ── Vendor bills (accounts payable) ────────────────────────────────────
    vendor_bills = (
        await db.execute(
            select(VendorBill)
            .where(VendorBill.organization_id == organization_id)
            .limit(MAX_RECORDS_PER_KIND)
        )
    ).scalars().all()
    for bill in vendor_bills:
        vendor_name = vendor_name_by_id.get(bill.vendor_id)
        chunks.append(
            {
                "source_type": SOURCE_VENDOR_BILL,
                "source_id": bill.id,
                "title": f"Vendor bill {bill.bill_number or ''}".strip(),
                "reference": "finance/accounts-payable",
                "content": _vendor_bill_text(bill, vendor_name),
            }
        )

    # ── Customer invoices (accounts receivable) ────────────────────────────
    invoices = (
        await db.execute(
            select(CustomerInvoice)
            .options(joinedload(CustomerInvoice.customer))
            .where(CustomerInvoice.organization_id == organization_id)
            .limit(MAX_RECORDS_PER_KIND)
        )
    ).scalars().all()
    for invoice in invoices:
        customer = getattr(invoice, "customer", None)
        customer_name = getattr(customer, "name", None) if customer else None
        chunks.append(
            {
                "source_type": SOURCE_CUSTOMER_INVOICE,
                "source_id": invoice.id,
                "title": f"Customer invoice {invoice.invoice_number or ''}".strip(),
                "reference": "finance/accounts-receivable",
                "content": _customer_invoice_text(invoice, customer_name),
            }
        )

    # ── Bank accounts ──────────────────────────────────────────────────────
    bank_accounts = (
        await db.execute(
            select(BankAccount)
            .where(BankAccount.organization_id == organization_id)
            .limit(MAX_RECORDS_PER_KIND)
        )
    ).scalars().all()
    for account in bank_accounts:
        chunks.append(
            {
                "source_type": SOURCE_BANK_ACCOUNT,
                "source_id": account.id,
                "title": f"Bank account: {account.name}",
                "reference": "finance/bank-reconciliation",
                "content": _bank_account_text(account),
            }
        )

    # ── Budgets ────────────────────────────────────────────────────────────
    budgets = (
        await db.execute(
            select(Budget)
            .where(Budget.organization_id == organization_id)
            .limit(MAX_RECORDS_PER_KIND)
        )
    ).scalars().all()
    for budget in budgets:
        chunks.append(
            {
                "source_type": SOURCE_BUDGET,
                "source_id": budget.id,
                "title": f"Budget: {budget.name}",
                "reference": "finance/budgeting",
                "content": _budget_text(budget),
            }
        )

    # ── Inspections ────────────────────────────────────────────────────────
    inspections = (
        await db.execute(
            select(Inspection)
            .where(Inspection.organization_id == organization_id)
            .limit(MAX_RECORDS_PER_KIND)
        )
    ).scalars().all()
    for inspection in inspections:
        office_name = office_name_by_id.get(inspection.office_id)
        chunks.append(
            {
                "source_type": SOURCE_INSPECTION,
                "source_id": inspection.id,
                "title": f"Inspection: {inspection.title}",
                "reference": "inspections",
                "content": _inspection_text(inspection, office_name),
            }
        )

    # ── Vacancy listings ───────────────────────────────────────────────────
    listings = (
        await db.execute(
            select(VacancyListing)
            .where(
                VacancyListing.organization_id == organization_id,
                VacancyListing.is_deleted.is_(False),
            )
            .limit(MAX_RECORDS_PER_KIND)
        )
    ).scalars().all()
    for listing in listings:
        unit_label = unit_label_by_id.get(listing.unit_id)
        chunks.append(
            {
                "source_type": SOURCE_LISTING,
                "source_id": listing.id,
                "title": f"Vacancy listing: {listing.title}",
                "reference": "residential/listings",
                "content": _listing_text(listing, unit_label),
            }
        )

    # ── Rental applications (leasing funnel) ───────────────────────────────
    applications = (
        await db.execute(
            select(RentalApplication)
            .where(
                RentalApplication.organization_id == organization_id,
                RentalApplication.is_deleted.is_(False),
            )
            .limit(MAX_RECORDS_PER_KIND)
        )
    ).scalars().all()
    application_label_by_id: dict[uuid.UUID, str] = {}
    for app in applications:
        label = _application_name(app)
        application_label_by_id[app.id] = label
        unit_label = unit_label_by_id.get(app.unit_id)
        chunks.append(
            {
                "source_type": SOURCE_RENTAL_APPLICATION,
                "source_id": app.id,
                "title": f"Rental application: {label}",
                "reference": "residential/applications",
                "content": _rental_application_text(app, unit_label),
            }
        )

    # ── Screening reports ──────────────────────────────────────────────────
    screening_reports = (
        await db.execute(
            select(ScreeningReport)
            .where(ScreeningReport.organization_id == organization_id)
            .limit(MAX_RECORDS_PER_KIND)
        )
    ).scalars().all()
    for report in screening_reports:
        applicant_label = application_label_by_id.get(report.application_id)
        chunks.append(
            {
                "source_type": SOURCE_SCREENING_REPORT,
                "source_id": report.id,
                "title": "Tenant screening report",
                "reference": "residential/applications",
                "content": _screening_report_text(report, applicant_label),
            }
        )

    # ── Generic catch-all: every remaining organization-scoped table ───────
    # So the assistant can answer questions about *any* data in the database,
    # not just the entities with a bespoke builder above. Each row becomes one
    # keyword/semantic-searchable chunk built by reflecting over its columns
    # (sensitive columns such as passwords/tokens are redacted).
    generic_counts = await _collect_generic_chunks(db, organization_id, chunks)

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
        "rental_units": len(units),
        "residents": len(residents),
        "resident_leases": len(resident_leases),
        "rent_charges": len(rent_charges),
        "owners": len(owners),
        "owner_distributions": len(distributions),
        "vendor_bills": len(vendor_bills),
        "customer_invoices": len(invoices),
        "bank_accounts": len(bank_accounts),
        "budgets": len(budgets),
        "inspections": len(inspections),
        "listings": len(listings),
        "applications": len(applications),
        "applications_screening": sum(
            1 for a in applications if a.status == "screening"
        ),
        "screening_reports": len(screening_reports),
    }
    chunks.insert(
        0,
        {
            "source_type": SOURCE_PORTFOLIO_SUMMARY,
            "source_id": organization_id,
            "title": "Portfolio summary (totals)",
            "reference": "dashboard",
            "content": _portfolio_summary_text(summary_counts, generic_counts),
        },
    )

    # Drop empty-content chunks (nothing useful to embed or match).
    return [c for c in chunks if c["content"]]


async def _collect_generic_chunks(
    db: AsyncSession, organization_id: uuid.UUID, chunks: list[dict]
) -> dict[str, int]:
    """Append one chunk per row for every generically-indexable table.

    Returns a ``{table: row_count}`` map so aggregate counts can be folded into
    the portfolio summary. Each query is explicitly organization-scoped (and
    soft-delete-aware when the model supports it) so no other org's rows are
    ever indexed.
    """
    generic_counts: dict[str, int] = {}
    for cls, mapper, table in _generic_indexable_models():
        stmt = select(cls).where(cls.organization_id == organization_id)
        if "is_deleted" in mapper.columns.keys():
            stmt = stmt.where(cls.is_deleted.is_(False))
        stmt = stmt.limit(_GENERIC_MAX_RECORDS_PER_TABLE)
        records = (await db.execute(stmt)).scalars().all()
        count = 0
        for record in records:
            source_id = getattr(record, "id", None)
            if not isinstance(source_id, uuid.UUID):
                continue
            content = _generic_record_text(record, mapper)
            if not content:
                continue
            chunks.append(
                {
                    "source_type": table,
                    "source_id": source_id,
                    "title": _generic_record_title(record, mapper, table),
                    "reference": None,
                    "content": content,
                }
            )
            count += 1
        if count:
            generic_counts[table] = count
    return generic_counts


async def reindex_organization(
    db: AsyncSession, organization_id: uuid.UUID
) -> int:
    """Rebuild the knowledge index for one organization. Returns chunk count.

    Idempotent: deletes the org's existing chunks and re-inserts a fresh set.
    Embeddings are added when Gemini is configured; otherwise chunks are stored
    keyword-only so retrieval still works.
    """
    if organization_id is None:
        raise ValueError("organization_id is required to (re)index knowledge")
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
    entity_type = chunk.entity_type or "lease"
    entity_id = chunk.entity_id or chunk.lease_id
    # Deep-link the citation back to its source record's list route.
    reference = f"{entity_type}/{entity_id}" if entity_id else None
    return {
        "source_type": "lease_document" if entity_type == "lease" else f"{entity_type}_document",
        "source_id": str(entity_id) if entity_id else None,
        "title": label,
        "reference": reference,
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
    # Strict org isolation: retrieval must always be scoped. A missing org could
    # otherwise scan the global index and leak another org's data — a failure.
    if organization_id is None:
        raise ValueError("organization_id is required for knowledge retrieval")

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


def _source_key(kind: str, chunk: object) -> tuple:
    """Stable identifier for the source record a scored chunk belongs to.

    Used to enforce per-source diversity so a single verbose lease/document does
    not dominate the retrieved context. Knowledge chunks are keyed by their
    originating entity, document chunks by their lease.
    """
    if kind == "document":
        return ("document", getattr(chunk, "attachment_id", None) or getattr(chunk, "lease_id", None))
    return ("knowledge", getattr(chunk, "source_type", None), getattr(chunk, "source_id", None))


def _select_relevant(
    scored: list[tuple[float, str, object]], *, limit: int
) -> list[tuple[float, str, object]]:
    """Pick the best, diverse, high-signal chunks from scored candidates.

    Applies an absolute and a best-relative similarity floor to drop weak
    chunks, then caps how many chunks any single source may contribute so the
    final context covers more distinct records. The single top-scoring chunk is
    always retained so a genuine-but-thin result set is never emptied.
    """
    if not scored:
        return []

    ranked = sorted(scored, key=lambda x: x[0], reverse=True)
    best_score = ranked[0][0]
    threshold = max(SEMANTIC_RELEVANCE_FLOOR, best_score * SEMANTIC_RELATIVE_FLOOR_RATIO)

    selected: list[tuple[float, str, object]] = []
    per_source: dict[tuple, int] = {}
    for score, kind, chunk in ranked:
        if len(selected) >= limit:
            break
        # Always keep the single best match; gate everything else on the floor.
        if selected and score < threshold:
            continue
        key = _source_key(kind, chunk)
        if per_source.get(key, 0) >= MAX_CHUNKS_PER_SOURCE:
            continue
        per_source[key] = per_source.get(key, 0) + 1
        selected.append((score, kind, chunk))

    return selected


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
    top = _select_relevant(scored, limit=limit)
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
