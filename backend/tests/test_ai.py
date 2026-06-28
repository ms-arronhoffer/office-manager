"""Tests for the AI-assist API (Google Gemini).

The Gemini client is always mocked — no real API key is exercised. These tests
assert entitlement gating (basic ingestion is open to all tiers; richer AI is
Pro+), graceful degradation when the key is unset, and schema mapping.
"""
import io

import pytest

from app.auth.jwt_handler import create_access_token
from app.auth.password import hash_password
from app.models.organization import Organization
from app.models.user import User
from app.services import ai_service


async def _make_org_user(db_session, plan: str, email: str) -> dict[str, str]:
    org = Organization(name=f"Org {plan}", slug=f"org-{plan}-{email[:3]}", plan=plan)
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    user = User(
        email=email,
        display_name="U",
        password_hash=hash_password("x"),
        auth_provider="internal",
        role="admin",
        is_active=True,
        organization_id=org.id,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return {"Authorization": "Bearer " + token}


def _doc():
    return ("lease.txt", io.BytesIO(b"Lessor: Acme. Commencement 2024-01-01."), "text/plain")


@pytest.mark.asyncio
async def test_status_reports_configuration(client, admin_user, monkeypatch):
    from tests.conftest import auth_headers

    monkeypatch.setattr(ai_service, "is_configured", lambda: False)
    resp = await client.get("/api/v1/ai/status", headers=auth_headers(admin_user))
    assert resp.status_code == 200, resp.text
    assert resp.json()["configured"] is False


@pytest.mark.asyncio
async def test_basic_lease_parse_allowed_on_starter(client, db_session, monkeypatch):
    """Basic lease ingestion must work on every tier (not gated by ai_assist)."""
    headers = await _make_org_user(db_session, "starter", "starter@test.com")

    async def fake_parse(content, mime_type, *, text_content=None):
        return {"lessor_name": "Acme", "lease_commencement": "2024-01-01"}

    monkeypatch.setattr(ai_service, "parse_lease_document", fake_parse)

    resp = await client.post("/api/v1/ai/leases/parse", headers=headers, files={"file": _doc()})
    assert resp.status_code == 200, resp.text
    assert resp.json()["suggested"]["lessor_name"] == "Acme"


@pytest.mark.asyncio
async def test_basic_lease_parse_degrades_when_unconfigured(client, db_session, monkeypatch):
    headers = await _make_org_user(db_session, "starter", "starter2@test.com")

    async def fake_parse(content, mime_type, *, text_content=None):
        raise ai_service.AIUnavailableError("AI assist is not configured")

    monkeypatch.setattr(ai_service, "parse_lease_document", fake_parse)

    resp = await client.post("/api/v1/ai/leases/parse", headers=headers, files={"file": _doc()})
    assert resp.status_code == 503, resp.text


@pytest.mark.asyncio
async def test_summary_gated_for_starter(client, db_session):
    headers = await _make_org_user(db_session, "starter", "starter3@test.com")
    resp = await client.post("/api/v1/ai/reports/summary", headers=headers, json={"period": "weekly"})
    assert resp.status_code == 402, resp.text


@pytest.mark.asyncio
async def test_summary_allowed_for_pro(client, db_session, monkeypatch):
    headers = await _make_org_user(db_session, "pro", "pro@test.com")

    async def fake_narrative(period_label, data):
        return f"Briefing for {period_label}."

    monkeypatch.setattr(ai_service, "generate_summary_narrative", fake_narrative)

    resp = await client.post("/api/v1/ai/reports/summary", headers=headers, json={"period": "weekly"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["period"] == "weekly"
    assert "Briefing for" in body["narrative"]
    assert "open_tickets" in body["data"]


@pytest.mark.asyncio
async def test_abstract_suggest_gated_for_starter(client, db_session):
    headers = await _make_org_user(db_session, "starter", "starter4@test.com")
    import uuid

    resp = await client.post(
        f"/api/v1/ai/leases/{uuid.uuid4()}/abstract/suggest",
        headers=headers,
        files={"file": _doc()},
    )
    assert resp.status_code == 402, resp.text


def _make_docx_bytes(text: str) -> bytes:
    import docx

    document = docx.Document()
    document.add_paragraph(text)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_lease_parse_accepts_docx_and_extracts_text(client, db_session, monkeypatch):
    """A .docx upload must be turned into text and passed to the model."""
    headers = await _make_org_user(db_session, "starter", "docx@test.com")

    captured: dict[str, object] = {}

    async def fake_parse(content, mime_type, *, text_content=None):
        captured["mime_type"] = mime_type
        captured["text_content"] = text_content
        return {"lessor_name": "Acme Properties"}

    monkeypatch.setattr(ai_service, "parse_lease_document", fake_parse)

    docx_bytes = _make_docx_bytes("Lessor: Acme Properties. Base Rent: $5,000/mo.")
    files = {
        "file": (
            "lease.docx",
            io.BytesIO(docx_bytes),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }
    resp = await client.post("/api/v1/ai/leases/parse", headers=headers, files=files)
    assert resp.status_code == 200, resp.text
    assert resp.json()["suggested"]["lessor_name"] == "Acme Properties"
    # The model received extracted text, not raw bytes.
    assert captured["text_content"] is not None
    assert "Acme Properties" in captured["text_content"]


@pytest.mark.asyncio
async def test_lease_parse_rejects_legacy_doc(client, db_session, monkeypatch):
    """Legacy .doc cannot be extracted in-process; expect a clear 400."""
    headers = await _make_org_user(db_session, "starter", "legacydoc@test.com")

    async def fake_parse(content, mime_type, *, text_content=None):  # pragma: no cover
        raise AssertionError("parse should not be reached for .doc")

    monkeypatch.setattr(ai_service, "parse_lease_document", fake_parse)

    files = {"file": ("lease.doc", io.BytesIO(b"\xd0\xcf\x11\xe0 legacy"), "application/msword")}
    resp = await client.post("/api/v1/ai/leases/parse", headers=headers, files=files)
    assert resp.status_code == 400, resp.text
    assert ".docx" in resp.json()["detail"].lower() or "convert" in resp.json()["detail"].lower()


async def _create_lease(client, headers) -> str:
    """Create a lease via the API and return its id."""
    resp = await client.post(
        "/api/v1/leases",
        headers=headers,
        json={"lease_name": "Abstract Source Lease", "expiration_year": 2030},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_abstract_suggest_passes_field_schema_to_model(client, db_session, monkeypatch):
    """The router must forward each category's field schema so the model can
    populate discrete fields (e.g. a relocation notice-days field) rather than
    only summary/notes."""
    headers = await _make_org_user(db_session, "pro", "abs-fields@test.com")
    lease_id = await _create_lease(client, headers)

    captured: dict[str, object] = {}

    async def fake_suggest(content, mime_type, categories, *, text_content=None):
        captured["categories"] = categories
        return {"relocation_right": {"relocation_notice_days": 60, "summary": "Yes."}}

    monkeypatch.setattr(ai_service, "suggest_abstract_clauses", fake_suggest)

    files = {"file": ("lease.txt", io.BytesIO(b"Landlord may relocate on 60 days notice."), "text/plain")}
    resp = await client.post(
        f"/api/v1/ai/leases/{lease_id}/abstract/suggest", headers=headers, files=files
    )
    assert resp.status_code == 200, resp.text

    categories = captured["categories"]
    by_key = {c["key"]: c for c in categories}
    assert "relocation_right" in by_key
    # Each category carries its full field schema (key/label/type), not just a name.
    field_keys = {f["key"] for f in by_key["relocation_right"]["fields"]}
    assert "relocation_notice_days" in field_keys


@pytest.mark.asyncio
async def test_suggest_abstract_prompt_includes_field_schema(monkeypatch):
    """The prompt sent to the model must enumerate each category's field keys
    and types so values land in the right fields."""
    captured: dict[str, object] = {}

    async def fake_generate(parts, **kwargs):
        captured["parts"] = parts
        return "{}"

    monkeypatch.setattr(ai_service, "_generate", fake_generate)

    categories = [
        {
            "key": "relocation_right",
            "name": "Relocation Right",
            "fields": [
                {"key": "relocation_notice_days", "label": "Relocation Notice (days)", "type": "number"},
                {"key": "summary", "label": "Summary", "type": "textarea"},
                {"key": "notes", "label": "Notes", "type": "textarea"},
            ],
        }
    ]
    await ai_service.suggest_abstract_clauses(
        b"", "text/plain", categories, text_content="Relocate on 60 days notice."
    )

    prompt_text = " ".join(
        p["text"] for p in captured["parts"] if isinstance(p, dict) and "text" in p
    )
    assert "relocation_notice_days" in prompt_text
    assert "number" in prompt_text


@pytest.mark.asyncio
async def test_abstract_suggest_extracts_text_for_txt(client, db_session, monkeypatch):
    """A .txt upload must be turned into text before the model is called.

    Regression: the abstract-suggest endpoint previously sent raw bytes inline
    for Word/text documents (which Gemini cannot read), so the lease abstract
    was never prefilled even though field-level parsing worked.
    """
    headers = await _make_org_user(db_session, "pro", "abs-txt@test.com")
    lease_id = await _create_lease(client, headers)

    captured: dict[str, object] = {}

    async def fake_suggest(content, mime_type, categories, *, text_content=None):
        captured["text_content"] = text_content
        return {"square_footage": {"summary": "Approx 5,000 RSF.", "notes": ""}}

    monkeypatch.setattr(ai_service, "suggest_abstract_clauses", fake_suggest)

    files = {"file": ("lease.txt", io.BytesIO(b"Rentable Area: 5,000 SF."), "text/plain")}
    resp = await client.post(
        f"/api/v1/ai/leases/{lease_id}/abstract/suggest", headers=headers, files=files
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["suggested"]["square_footage"]["summary"] == "Approx 5,000 RSF."
    # The model received extracted text, not raw inline bytes.
    assert captured["text_content"] is not None
    assert "5,000 SF" in captured["text_content"]


@pytest.mark.asyncio
async def test_abstract_suggest_accepts_docx_and_extracts_text(client, db_session, monkeypatch):
    """A .docx upload must be converted to text for abstract suggestions too."""
    headers = await _make_org_user(db_session, "pro", "abs-docx@test.com")
    lease_id = await _create_lease(client, headers)

    captured: dict[str, object] = {}

    async def fake_suggest(content, mime_type, categories, *, text_content=None):
        captured["text_content"] = text_content
        return {"rent_expiration": {"summary": "Base rent $5,000/mo.", "notes": ""}}

    monkeypatch.setattr(ai_service, "suggest_abstract_clauses", fake_suggest)

    docx_bytes = _make_docx_bytes("Base Rent: $5,000 per month. Term expires 2030.")
    files = {
        "file": (
            "lease.docx",
            io.BytesIO(docx_bytes),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }
    resp = await client.post(
        f"/api/v1/ai/leases/{lease_id}/abstract/suggest", headers=headers, files=files
    )
    assert resp.status_code == 200, resp.text
    assert captured["text_content"] is not None
    assert "5,000" in captured["text_content"]


@pytest.mark.asyncio
async def test_abstract_suggest_sends_pdf_bytes_inline(client, db_session, monkeypatch):
    """PDFs/images are still sent inline (no text extraction)."""
    headers = await _make_org_user(db_session, "pro", "abs-pdf@test.com")
    lease_id = await _create_lease(client, headers)

    captured: dict[str, object] = {}

    async def fake_suggest(content, mime_type, categories, *, text_content=None):
        captured["text_content"] = text_content
        captured["mime_type"] = mime_type
        return {}

    monkeypatch.setattr(ai_service, "suggest_abstract_clauses", fake_suggest)

    files = {"file": ("lease.pdf", io.BytesIO(b"%PDF-1.4 fake pdf bytes"), "application/pdf")}
    resp = await client.post(
        f"/api/v1/ai/leases/{lease_id}/abstract/suggest", headers=headers, files=files
    )
    assert resp.status_code == 200, resp.text
    assert captured["text_content"] is None
    assert captured["mime_type"] == "application/pdf"


@pytest.mark.asyncio
async def test_ticket_triage_gated_for_starter(client, db_session):
    headers = await _make_org_user(db_session, "starter", "triage-starter@test.com")
    resp = await client.post(
        "/api/v1/ai/tickets/triage",
        headers=headers,
        json={"subject": "No heat", "description": "Furnace is dead."},
    )
    assert resp.status_code == 402, resp.text


@pytest.mark.asyncio
async def test_ticket_triage_allowed_for_pro(client, db_session, monkeypatch):
    headers = await _make_org_user(db_session, "pro", "triage-pro@test.com")

    async def fake_triage(subject, description, categories, vendors):
        return {
            "category_id": None,
            "category_name": "HVAC",
            "priority": "high",
            "vendor_id": None,
            "vendor_name": None,
            "reasoning": "No heat is urgent.",
            "draft_response": "Thanks, we're dispatching a technician.",
        }

    monkeypatch.setattr(ai_service, "triage_ticket", fake_triage)

    resp = await client.post(
        "/api/v1/ai/tickets/triage",
        headers=headers,
        json={"subject": "No heat", "description": "Furnace is dead."},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["suggested"]["priority"] == "high"


@pytest.mark.asyncio
async def test_ticket_triage_forwards_org_categories_and_vendors(client, db_session, monkeypatch):
    """The router must ground the model in the org's own categories and vendors."""
    from sqlalchemy import select as _select

    from app.models.maintenance_ticket import TicketCategory
    from app.models.user import User
    from app.models.vendor import Vendor

    email = "triage-ground@test.com"
    headers = await _make_org_user(db_session, "pro", email)
    user = (
        await db_session.execute(_select(User).where(User.email == email))
    ).scalar_one()
    org_uuid = user.organization_id

    db_session.add(TicketCategory(name="Plumbing", organization_id=org_uuid))
    db_session.add(
        Vendor(company_name="Acme Plumbing", services="plumbing, drains", organization_id=org_uuid)
    )
    await db_session.commit()

    captured: dict[str, object] = {}

    async def fake_triage(subject, description, categories, vendors):
        captured["categories"] = categories
        captured["vendors"] = vendors
        return {"priority": "medium"}

    monkeypatch.setattr(ai_service, "triage_ticket", fake_triage)

    resp = await client.post(
        "/api/v1/ai/tickets/triage",
        headers=headers,
        json={"subject": "Leak", "description": "Sink is leaking."},
    )
    assert resp.status_code == 200, resp.text
    cat_names = {c["name"] for c in captured["categories"]}
    vendor_names = {v["name"] for v in captured["vendors"]}
    assert "Plumbing" in cat_names
    assert "Acme Plumbing" in vendor_names


# ── Portfolio Q&A (RAG "Ask your portfolio") ──────────────────────────────────


async def _make_lease(db_session, org_id, name="Acme HQ Lease"):
    from app.models.lease import Lease

    lease = Lease(lease_name=name, organization_id=org_id, expiration_year=2030)
    db_session.add(lease)
    await db_session.commit()
    await db_session.refresh(lease)
    return lease


async def _add_chunk(db_session, org_id, lease_id, content, *, filename="lease.pdf"):
    from app.models.lease_document_chunk import LeaseDocumentChunk

    db_session.add(
        LeaseDocumentChunk(
            organization_id=org_id,
            lease_id=lease_id,
            attachment_id=None,
            source_filename=filename,
            chunk_index=0,
            content=content,
            embedding=None,
        )
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_portfolio_ask_gated_for_starter(client, db_session):
    headers = await _make_org_user(db_session, "starter", "ask-starter@test.com")
    resp = await client.post(
        "/api/v1/ai/portfolio/ask",
        headers=headers,
        json={"question": "Which leases expire in 2026?"},
    )
    assert resp.status_code == 402, resp.text


@pytest.mark.asyncio
async def test_portfolio_ask_grounds_answer_in_retrieved_chunks(client, db_session, monkeypatch):
    """The endpoint retrieves relevant chunks, feeds them to generation, and
    returns the answer with citations back to those chunks."""
    from sqlalchemy import select as _select

    from app.models.user import User

    email = "ask-pro@test.com"
    headers = await _make_org_user(db_session, "pro", email)
    user = (
        await db_session.execute(_select(User).where(User.email == email))
    ).scalar_one()
    org_id = user.organization_id

    # Keyword retrieval path (no Gemini embeddings needed).
    monkeypatch.setattr(ai_service, "is_configured", lambda: False)
    lease = await _make_lease(db_session, org_id, "Co-Tenancy Lease")
    await _add_chunk(
        db_session,
        org_id,
        lease.id,
        "The co-tenancy clause expires on 2026-06-30 unless renewed by the tenant.",
    )

    captured: dict[str, object] = {}

    async def fake_answer(question, context_chunks, **kwargs):
        captured["question"] = question
        captured["context_chunks"] = context_chunks
        return "The co-tenancy clause expires in 2026 [1]."

    monkeypatch.setattr(ai_service, "answer_portfolio_question", fake_answer)

    resp = await client.post(
        "/api/v1/ai/portfolio/ask",
        headers=headers,
        json={"question": "Which leases have a co-tenancy clause expiring in 2026?"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["grounded"] is True
    assert "2026" in body["answer"]
    assert len(body["citations"]) == 1
    citation = body["citations"][0]
    assert citation["index"] == 1
    assert citation["lease_id"] == str(lease.id)
    assert citation["lease_name"] == "Co-Tenancy Lease"
    # The retrieved chunk was forwarded to the generation step with a citation id.
    forwarded = captured["context_chunks"]
    assert forwarded[0]["index"] == 1
    assert "co-tenancy" in (forwarded[0]["snippet"] or "").lower()


@pytest.mark.asyncio
async def test_portfolio_ask_no_matches_returns_ungrounded(client, db_session, monkeypatch):
    """With no relevant documents the model is never called and the answer
    reports the gap with ``grounded=False``."""
    headers = await _make_org_user(db_session, "pro", "ask-empty@test.com")
    monkeypatch.setattr(ai_service, "is_configured", lambda: False)

    async def fail_answer(question, context_chunks, **kwargs):  # pragma: no cover
        raise AssertionError("generation should not run with no matches")

    monkeypatch.setattr(ai_service, "answer_portfolio_question", fail_answer)

    resp = await client.post(
        "/api/v1/ai/portfolio/ask",
        headers=headers,
        json={"question": "Anything about indemnification?"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["grounded"] is False
    assert body["citations"] == []


@pytest.mark.asyncio
async def test_portfolio_ask_degrades_when_generation_unconfigured(client, db_session, monkeypatch):
    """When matches exist but generation is unconfigured, surface a clear 503."""
    from sqlalchemy import select as _select

    from app.models.user import User

    email = "ask-degrade@test.com"
    headers = await _make_org_user(db_session, "pro", email)
    user = (
        await db_session.execute(_select(User).where(User.email == email))
    ).scalar_one()
    org_id = user.organization_id

    monkeypatch.setattr(ai_service, "is_configured", lambda: False)
    lease = await _make_lease(db_session, org_id, "CAM Lease")
    await _add_chunk(
        db_session,
        org_id,
        lease.id,
        "Tenant's share of common area maintenance is capped at 5% annually.",
    )

    async def unavailable(question, context_chunks, **kwargs):
        raise ai_service.AIUnavailableError("AI assist is not configured")

    monkeypatch.setattr(ai_service, "answer_portfolio_question", unavailable)

    resp = await client.post(
        "/api/v1/ai/portfolio/ask",
        headers=headers,
        json={"question": "What is our CAM exposure?"},
    )
    assert resp.status_code == 503, resp.text


@pytest.mark.asyncio
async def test_answer_portfolio_question_builds_cited_prompt(monkeypatch):
    """The generation prompt must enumerate excerpts with their citation ids so
    the model can attribute claims."""
    captured: dict[str, object] = {}

    async def fake_generate(parts, **kwargs):
        captured["parts"] = parts
        captured["system"] = kwargs.get("system_instruction")
        return "Answer [1]."

    monkeypatch.setattr(ai_service, "_generate", fake_generate)

    chunks = [
        {
            "index": 1,
            "lease_name": "Northeast Plaza",
            "source_filename": "lease.pdf",
            "snippet": "CAM charges are estimated at $42,000 per year.",
        }
    ]
    answer = await ai_service.answer_portfolio_question("Total CAM exposure?", chunks)
    assert answer == "Answer [1]."

    prompt_text = " ".join(
        p["text"] for p in captured["parts"] if isinstance(p, dict) and "text" in p
    )
    assert "[1]" in prompt_text
    assert "Northeast Plaza" in prompt_text
    assert "CAM charges" in prompt_text
    assert "cite" in (captured["system"] or "").lower()


# ── Broadened summary inputs + AI-recommended actions ─────────────────────────


async def _org_for(db_session, email: str):
    """Create an org + admin user, returning (headers, organization)."""
    from app.models.organization import Organization

    org = Organization(name=f"Org {email}", slug=f"org-{email[:8]}", plan="pro")
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    user = User(
        email=email,
        display_name="U",
        password_hash=hash_password("x"),
        auth_provider="internal",
        role="admin",
        is_active=True,
        organization_id=org.id,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return {"Authorization": "Bearer " + token}, org


@pytest.mark.asyncio
async def test_aggregate_summary_includes_broadened_inputs(db_session):
    """COIs, HVAC renewals and past-due payables are aggregated org-scoped."""
    from datetime import date, timedelta

    from app.models.general_ledger import GLAccount
    from app.models.hvac_contract import HvacContract
    from app.models.insurance_certificate import InsuranceCertificate
    from app.models.vendor import Vendor
    from app.models.vendor_bill import VendorBill, VendorBillLine
    from app.routers.ai import _aggregate_summary

    _, org = await _org_for(db_session, "broaden@test.com")
    today = date.today()

    # Vendor + expiring COI
    vendor = Vendor(organization_id=org.id, company_name="Acme HVAC")
    db_session.add(vendor)
    await db_session.commit()
    await db_session.refresh(vendor)

    db_session.add(
        InsuranceCertificate(
            organization_id=org.id,
            vendor_id=vendor.id,
            certificate_type="general_liability",
            insurer="State Farm",
            expiration_date=today + timedelta(days=10),
        )
    )

    # HVAC renewal due soon
    db_session.add(
        HvacContract(
            organization_id=org.id,
            office_name="Suite 100",
            hvac_company="CoolAir",
            next_service_date=today + timedelta(days=5),
        )
    )

    # Past-due, finalized, unpaid vendor bill
    account = GLAccount(
        organization_id=org.id, code="6000", name="Repairs", type="expense"
    )
    db_session.add(account)
    await db_session.commit()
    await db_session.refresh(account)

    bill = VendorBill(
        organization_id=org.id,
        vendor_id=vendor.id,
        bill_number="INV-1",
        bill_date=today - timedelta(days=60),
        due_date=today - timedelta(days=15),
        status="finalized",
        total_amount=500,
    )
    db_session.add(bill)
    await db_session.commit()
    await db_session.refresh(bill)
    db_session.add(
        VendorBillLine(bill_id=bill.id, account_id=account.id, amount=500)
    )
    await db_session.commit()

    data = await _aggregate_summary(db_session, org.id, horizon_days=30)

    assert len(data["expiring_cois"]) == 1
    assert data["expiring_cois"][0]["holder"] == "Acme HVAC"

    assert len(data["hvac_renewals"]) == 1
    assert data["hvac_renewals"][0]["office"] == "Suite 100"

    assert len(data["past_due_payables"]) == 1
    payable = data["past_due_payables"][0]
    assert payable["vendor"] == "Acme HVAC"
    assert payable["balance_due"] == 500.0
    assert payable["days_overdue"] == 15


@pytest.mark.asyncio
async def test_summary_returns_recommended_actions(client, db_session, monkeypatch):
    headers, _ = await _org_for(db_session, "actions@test.com")

    async def fake_narrative(period_label, data):
        return f"Briefing for {period_label}."

    async def fake_actions(period_label, data):
        return [
            {
                "title": "Renew Acme COI",
                "detail": "Expires in 10 days.",
                "priority": "high",
                "category": "insurance",
            }
        ]

    monkeypatch.setattr(ai_service, "generate_summary_narrative", fake_narrative)
    monkeypatch.setattr(ai_service, "generate_recommended_actions", fake_actions)

    resp = await client.post(
        "/api/v1/ai/reports/summary", headers=headers, json={"period": "weekly"}
    )
    assert resp.status_code == 200, resp.text
    actions = resp.json()["recommended_actions"]
    assert len(actions) == 1
    assert actions[0]["title"] == "Renew Acme COI"
    assert actions[0]["priority"] == "high"


@pytest.mark.asyncio
async def test_summary_survives_actions_failure(client, db_session, monkeypatch):
    """A failure generating actions must not fail the whole briefing."""
    headers, _ = await _org_for(db_session, "actionsfail@test.com")

    async def fake_narrative(period_label, data):
        return "Narrative body."

    async def boom(period_label, data):
        raise ai_service.AIRequestError("model error")

    monkeypatch.setattr(ai_service, "generate_summary_narrative", fake_narrative)
    monkeypatch.setattr(ai_service, "generate_recommended_actions", boom)

    resp = await client.post(
        "/api/v1/ai/reports/summary", headers=headers, json={"period": "weekly"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["recommended_actions"] == []


@pytest.mark.asyncio
async def test_generate_recommended_actions_normalizes_output(monkeypatch):
    """Malformed model output is coerced into clean, bounded action dicts."""

    async def fake_generate(parts, **kwargs):
        return (
            '{"actions": [{"title": "Do X", "priority": "URGENT", "category": "lease"},'
            ' {"detail": "no title"}, {"title": "Do Y"}]}'
        )

    monkeypatch.setattr(ai_service, "_generate", fake_generate)

    actions = await ai_service.generate_recommended_actions("Week", {})
    # second item dropped (no title); priorities normalised; defaults filled
    assert len(actions) == 2
    assert actions[0]["title"] == "Do X"
    assert actions[0]["priority"] == "medium"  # unknown priority -> medium
    assert actions[0]["category"] == "lease"
    assert actions[1]["title"] == "Do Y"
    assert actions[1]["category"] == "other"


def test_actions_to_markdown_renders_section():
    md = ai_service.actions_to_markdown(
        [{"title": "Renew COI", "detail": "Soon.", "priority": "high", "category": "insurance"}]
    )
    assert "## AI-Recommended Actions" in md
    assert "[HIGH] Renew COI" in md
    assert "Soon." in md
    assert ai_service.actions_to_markdown([]) == ""


# ── Inbound document classification & routing ─────────────────────────────────


@pytest.mark.asyncio
async def test_document_classify_gated_for_starter(client, db_session):
    """Inbound classification is a Pro+ (ai_assist) feature."""
    headers = await _make_org_user(db_session, "starter", "classify-starter@test.com")
    resp = await client.post(
        "/api/v1/ai/documents/classify", headers=headers, files={"file": _doc()}
    )
    assert resp.status_code == 402, resp.text


@pytest.mark.asyncio
async def test_document_classify_routes_invoice_to_vendor(client, db_session, monkeypatch):
    """A vendor invoice is classified and matched to the org's vendor."""
    from sqlalchemy import select as _select

    from app.models.user import User
    from app.models.vendor import Vendor

    email = "classify-invoice@test.com"
    headers = await _make_org_user(db_session, "pro", email)
    user = (
        await db_session.execute(_select(User).where(User.email == email))
    ).scalar_one()
    org_uuid = user.organization_id

    db_session.add(Vendor(company_name="Acme Plumbing LLC", organization_id=org_uuid))
    await db_session.commit()

    async def fake_classify(content, mime_type, *, text_content=None):
        return {
            "document_type": "vendor_invoice",
            "confidence": "high",
            "reasoning": "Has an invoice number and total.",
            "fields": {"vendor_name": "Acme Plumbing", "total_amount": 1200},
        }

    monkeypatch.setattr(ai_service, "classify_document", fake_classify)

    resp = await client.post(
        "/api/v1/ai/documents/classify", headers=headers, files={"file": _doc()}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["document_type"] == "vendor_invoice"
    assert body["confidence"] == "high"
    matches = body["suggested_matches"]
    assert any(
        m["entity_type"] == "vendor" and m["name"] == "Acme Plumbing LLC"
        for m in matches
    )


@pytest.mark.asyncio
async def test_document_classify_degrades_when_unconfigured(client, db_session, monkeypatch):
    headers = await _make_org_user(db_session, "pro", "classify-degrade@test.com")

    async def fake_classify(content, mime_type, *, text_content=None):
        raise ai_service.AIUnavailableError("not configured")

    monkeypatch.setattr(ai_service, "classify_document", fake_classify)

    resp = await client.post(
        "/api/v1/ai/documents/classify", headers=headers, files={"file": _doc()}
    )
    assert resp.status_code == 503, resp.text


@pytest.mark.asyncio
async def test_normalize_classification_restricts_fields_and_type():
    """Unknown types collapse to 'unknown' and stray fields are dropped."""
    result = ai_service._normalize_classification(
        {
            "document_type": "vendor_invoice",
            "confidence": "VERY HIGH",
            "reasoning": "x",
            "fields": {"vendor_name": "Acme", "not_a_field": "drop me"},
        }
    )
    assert result["document_type"] == "vendor_invoice"
    assert result["confidence"] == "low"  # invalid confidence -> low
    assert result["fields"] == {"vendor_name": "Acme"}

    bogus = ai_service._normalize_classification({"document_type": "spaceship"})
    assert bogus["document_type"] == "unknown"
    assert bogus["fields"] == {}


@pytest.mark.asyncio
async def test_classify_document_prompt_lists_all_types(monkeypatch):
    """The classification prompt must enumerate every supported document type."""
    captured: dict[str, object] = {}

    async def fake_generate(parts, **kwargs):
        captured["parts"] = parts
        return (
            '{"document_type": "insurance_certificate", "confidence": "medium",'
            ' "reasoning": "ACORD form", "fields": {"insurer": "Hartford"}}'
        )

    monkeypatch.setattr(ai_service, "_generate", fake_generate)

    result = await ai_service.classify_document(
        b"", "application/pdf", text_content="Certificate of Liability Insurance"
    )
    assert result["document_type"] == "insurance_certificate"
    prompt_text = " ".join(p.get("text", "") for p in captured["parts"])
    for doc_type in ("vendor_invoice", "insurance_certificate", "lease_amendment"):
        assert doc_type in prompt_text


# ─── Lease abstract gap-detection (Feature 6) ────────────────────────────────

@pytest.mark.asyncio
async def test_abstract_gaps_gated_for_starter(client, db_session):
    headers = await _make_org_user(db_session, "starter", "gaps-starter@test.com")
    import uuid

    resp = await client.post(
        f"/api/v1/ai/leases/{uuid.uuid4()}/abstract/gaps", headers=headers
    )
    assert resp.status_code == 402, resp.text


@pytest.mark.asyncio
async def test_abstract_gaps_missing_lease(client, db_session):
    headers = await _make_org_user(db_session, "pro", "gaps-404@test.com")
    import uuid

    resp = await client.post(
        f"/api/v1/ai/leases/{uuid.uuid4()}/abstract/gaps", headers=headers
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_abstract_gaps_enriches_and_passes_captured_content(
    client, db_session, monkeypatch
):
    """The endpoint forwards captured clause content and enriches findings with
    the category name/group from the catalog."""
    headers = await _make_org_user(db_session, "pro", "gaps-ok@test.com")
    lease_id = await _create_lease(client, headers)

    # Capture content for one clause so the reviewer can judge completeness.
    put = await client.put(
        f"/api/v1/leases/{lease_id}/abstract/lease_options",
        headers=headers,
        json={"content": {"option_type": "renewal"}},
    )
    assert put.status_code == 200, put.text

    captured: dict = {}

    async def fake_gaps(categories, captured_clauses, *, content=b"", mime_type="", text_content=None):
        captured["categories"] = categories
        captured["captured"] = captured_clauses
        return [
            {
                "category_key": "sublease_assignment",
                "gap_type": "missing",
                "severity": "high",
                "message": "No assignment clause found",
                "recommendation": "Confirm whether the lease permits assignment.",
            },
            {
                "category_key": "lease_options",
                "gap_type": "incomplete",
                "severity": "medium",
                "message": "Renewal option terms incomplete",
                "recommendation": "Capture the notice period and exercise window.",
            },
            # Unknown category keys are dropped by normalization upstream; an
            # already-known one with no message would be dropped too.
        ]

    monkeypatch.setattr(ai_service, "detect_abstract_gaps", fake_gaps)

    resp = await client.post(
        f"/api/v1/ai/leases/{lease_id}/abstract/gaps", headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    gaps = {g["category_key"]: g for g in body["gaps"]}
    assert gaps["sublease_assignment"]["name"] == "Sublease/Assignment"
    assert gaps["sublease_assignment"]["group"] == "rights"
    assert gaps["lease_options"]["gap_type"] == "incomplete"

    # The captured lease_options content reached the service.
    assert captured["captured"]["lease_options"]["content"] == {"option_type": "renewal"}


@pytest.mark.asyncio
async def test_abstract_gaps_extracts_uploaded_document_text(
    client, db_session, monkeypatch
):
    headers = await _make_org_user(db_session, "pro", "gaps-doc@test.com")
    lease_id = await _create_lease(client, headers)

    captured: dict = {}

    async def fake_gaps(categories, captured_clauses, *, content=b"", mime_type="", text_content=None):
        captured["text_content"] = text_content
        return []

    monkeypatch.setattr(ai_service, "detect_abstract_gaps", fake_gaps)

    files = {"file": ("lease.txt", io.BytesIO(b"This lease has no assignment provision."), "text/plain")}
    resp = await client.post(
        f"/api/v1/ai/leases/{lease_id}/abstract/gaps", headers=headers, files=files
    )
    assert resp.status_code == 200, resp.text
    assert captured["text_content"] is not None
    assert "assignment" in captured["text_content"]


@pytest.mark.asyncio
async def test_detect_abstract_gaps_normalizes_model_output(monkeypatch):
    """Unknown category keys / messageless items are dropped; bad enums default."""
    async def fake_generate(parts, **kwargs):
        return (
            '{"gaps": ['
            '{"category_key": "sublease_assignment", "gap_type": "weird", '
            '"severity": "urgent", "message": "No assignment clause found"},'
            '{"category_key": "not_a_real_key", "gap_type": "missing", '
            '"severity": "high", "message": "x"},'
            '{"category_key": "lease_options", "gap_type": "missing", '
            '"severity": "high", "message": ""}'
            ']}'
        )

    monkeypatch.setattr(ai_service, "_generate", fake_generate)

    categories = [
        {"key": "sublease_assignment", "name": "Sublease/Assignment", "fields": []},
        {"key": "lease_options", "name": "Lease Options", "fields": []},
    ]
    gaps = await ai_service.detect_abstract_gaps(categories, {})
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap["category_key"] == "sublease_assignment"
    # Invalid enums fall back to safe defaults.
    assert gap["gap_type"] == "incomplete"
    assert gap["severity"] == "medium"


@pytest.mark.asyncio
async def test_review_cam_reconciliation_normalizes_anomalies(monkeypatch):
    captured: dict = {}

    async def fake_generate(parts, **kwargs):
        captured["parts"] = parts
        return (
            '{"summary": "ok", "anomalies": ['
            '{"category": "marketing", "anomaly_type": "bogus", '
            '"severity": "critical", "message": "Not permitted"},'
            '{"anomaly_type": "year_over_year", "severity": "high", "message": ""}'
            ']}'
        )

    monkeypatch.setattr(ai_service, "_generate", fake_generate)

    result = await ai_service.review_cam_reconciliation(
        year=2025,
        lines=[{"category": "marketing", "actual_amount": 50000}],
        prior_year=2024,
        prior_lines=[{"category": "cam", "actual_amount": 100000}],
        lease_clauses={"Expense/Recoverables": {"content": {"recoverable_expenses": "CAM only"}}},
    )
    assert result["summary"] == "ok"
    assert len(result["anomalies"]) == 1
    anomaly = result["anomalies"][0]
    assert anomaly["anomaly_type"] == "other"  # bogus -> other
    assert anomaly["severity"] == "medium"  # critical -> medium
    # Prior-year data is embedded in the prompt.
    prompt_text = " ".join(p["text"] for p in captured["parts"] if "text" in p)
    assert "2024" in prompt_text
