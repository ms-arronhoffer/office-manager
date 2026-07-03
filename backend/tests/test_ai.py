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
async def test_lease_template_draft_from_document(client, db_session, monkeypatch):
    """AI drafts a reusable lease template (with merge fields) from a document."""
    headers = await _make_org_user(db_session, "starter", "tmpl@test.com")

    captured = {}

    async def fake_draft(content, mime_type, *, text_content=None):
        captured["text_content"] = text_content
        return {
            "name": "Residential Lease",
            "description": "Standard 12-month lease",
            "body": "This lease is between {{landlord_name}} and {{tenant_name}}.",
        }

    monkeypatch.setattr(ai_service, "draft_lease_template_from_document", fake_draft)

    resp = await client.post(
        "/api/v1/ai/lease-templates/parse", headers=headers, files={"file": _doc()}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Residential Lease"
    assert "{{tenant_name}}" in body["body"]
    # A .txt document is extracted to text before being sent to the model.
    assert captured["text_content"] is not None


@pytest.mark.asyncio
async def test_lease_template_draft_degrades_when_unconfigured(client, db_session, monkeypatch):
    headers = await _make_org_user(db_session, "starter", "tmpl2@test.com")

    async def fake_draft(content, mime_type, *, text_content=None):
        raise ai_service.AIUnavailableError("AI assist is not configured")

    monkeypatch.setattr(ai_service, "draft_lease_template_from_document", fake_draft)

    resp = await client.post(
        "/api/v1/ai/lease-templates/parse", headers=headers, files={"file": _doc()}
    )
    assert resp.status_code == 503, resp.text


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


def test_portfolio_system_prompts_carry_grounding_guidance():
    """Both RAG system prompts must enforce citation discipline and forbid
    invention so answers stay grounded in retrieved context."""
    for prompt in (ai_service.PORTFOLIO_QA_SYSTEM, ai_service.PORTFOLIO_ASSISTANT_SYSTEM):
        lowered = prompt.lower()
        assert "cite" in lowered
        assert "never invent" in lowered
        assert "[1]" in prompt  # worked few-shot example with a citation id


class _FakeChunk:
    """Minimal stand-in for a scored chunk used by retrieval selection tests."""

    def __init__(self, *, lease_id=None, source_type=None, source_id=None):
        self.lease_id = lease_id
        self.source_type = source_type
        self.source_id = source_id


def test_select_relevant_drops_weak_chunks_below_floor():
    from app.services import knowledge_service as ks

    strong = (0.9, "knowledge", _FakeChunk(source_type="office", source_id="a"))
    weak = (0.05, "knowledge", _FakeChunk(source_type="office", source_id="b"))
    selected = ks._select_relevant([strong, weak], limit=8)
    assert strong in selected
    assert weak not in selected  # below the absolute + relative floor


def test_select_relevant_always_keeps_top_match():
    from app.services import knowledge_service as ks

    # Even an only-weak result set must still surface its single best chunk.
    only = (0.01, "knowledge", _FakeChunk(source_type="office", source_id="a"))
    selected = ks._select_relevant([only], limit=8)
    assert selected == [only]


def test_select_relevant_caps_chunks_per_source():
    from app.services import knowledge_service as ks

    lease_id = "lease-1"
    same_source = [
        (0.9 - i * 0.01, "document", _FakeChunk(lease_id=lease_id))
        for i in range(6)
    ]
    other = (0.7, "document", _FakeChunk(lease_id="lease-2"))
    selected = ks._select_relevant(same_source + [other], limit=8)
    from_lease_1 = [s for s in selected if s[2].lease_id == lease_id]
    assert len(from_lease_1) == ks.MAX_CHUNKS_PER_SOURCE
    assert other in selected  # diversity keeps room for the other source


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


# ── Phase 1: document extraction for AP bills, insurance, HVAC contracts ──────

@pytest.mark.asyncio
async def test_vendor_bill_parse_allowed_on_starter(client, db_session, monkeypatch):
    """AP invoice extraction is open to all tiers (like lease parse)."""
    headers = await _make_org_user(db_session, "starter", "ap-parse@test.com")

    async def fake_parse(content, mime_type, *, text_content=None):
        return {"vendor_name": "Acme HVAC", "total_amount": 1250.5}

    monkeypatch.setattr(ai_service, "parse_vendor_bill_document", fake_parse)

    files = {"file": ("invoice.txt", io.BytesIO(b"Invoice total $1,250.50"), "text/plain")}
    resp = await client.post("/api/v1/ai/ap/parse", headers=headers, files=files)
    assert resp.status_code == 200, resp.text
    assert resp.json()["suggested"]["vendor_name"] == "Acme HVAC"


@pytest.mark.asyncio
async def test_vendor_bill_parse_degrades_when_unconfigured(client, db_session, monkeypatch):
    headers = await _make_org_user(db_session, "starter", "ap-503@test.com")

    async def fake_parse(content, mime_type, *, text_content=None):
        raise ai_service.AIUnavailableError("AI assist is not configured")

    monkeypatch.setattr(ai_service, "parse_vendor_bill_document", fake_parse)

    files = {"file": ("invoice.txt", io.BytesIO(b"x"), "text/plain")}
    resp = await client.post("/api/v1/ai/ap/parse", headers=headers, files=files)
    assert resp.status_code == 503, resp.text


@pytest.mark.asyncio
async def test_insurance_parse_extracts_text_for_docx(client, db_session, monkeypatch):
    """A .docx COI upload must be converted to text before the model is called."""
    headers = await _make_org_user(db_session, "starter", "coi-parse@test.com")

    captured: dict[str, object] = {}

    async def fake_parse(content, mime_type, *, text_content=None):
        captured["text_content"] = text_content
        return {"insurer": "Travelers", "certificate_type": "General Liability"}

    monkeypatch.setattr(ai_service, "parse_insurance_certificate", fake_parse)

    docx_bytes = _make_docx_bytes("Insurer: Travelers. Coverage: General Liability $1M.")
    files = {
        "file": (
            "coi.docx",
            io.BytesIO(docx_bytes),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }
    resp = await client.post("/api/v1/ai/insurance/parse", headers=headers, files=files)
    assert resp.status_code == 200, resp.text
    assert resp.json()["suggested"]["insurer"] == "Travelers"
    assert captured["text_content"] is not None
    assert "Travelers" in captured["text_content"]


@pytest.mark.asyncio
async def test_hvac_contract_parse_sends_pdf_inline(client, db_session, monkeypatch):
    """PDFs are sent inline (no text extraction) for HVAC contract parsing."""
    headers = await _make_org_user(db_session, "starter", "hvac-parse@test.com")

    captured: dict[str, object] = {}

    async def fake_parse(content, mime_type, *, text_content=None):
        captured["text_content"] = text_content
        captured["mime_type"] = mime_type
        return {"hvac_company": "CoolAir Inc"}

    monkeypatch.setattr(ai_service, "parse_hvac_contract", fake_parse)

    files = {"file": ("contract.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")}
    resp = await client.post("/api/v1/ai/hvac-contracts/parse", headers=headers, files=files)
    assert resp.status_code == 200, resp.text
    assert captured["text_content"] is None
    assert captured["mime_type"] == "application/pdf"


@pytest.mark.asyncio
async def test_parse_cache_short_circuits_identical_calls(monkeypatch):
    """An identical (parser, document) parse is served from cache without a
    second provider round-trip."""
    ai_service.clear_parse_cache()
    calls = {"n": 0}

    async def fake_generate(parts, **kwargs):
        calls["n"] += 1
        return '{"vendor_name": "Acme"}'

    monkeypatch.setattr(ai_service, "_generate", fake_generate)

    first = await ai_service.parse_vendor_bill_document(
        b"", "text/plain", text_content="Invoice from Acme"
    )
    second = await ai_service.parse_vendor_bill_document(
        b"", "text/plain", text_content="Invoice from Acme"
    )
    assert first == second == {"vendor_name": "Acme"}
    assert calls["n"] == 1  # second call hit the cache

    # A different document must NOT hit the cache.
    await ai_service.parse_vendor_bill_document(
        b"", "text/plain", text_content="Invoice from Other Co"
    )
    assert calls["n"] == 2
    ai_service.clear_parse_cache()


# ── Phase 2: maintenance ticket intelligence ──────────────────────────────────

async def _make_org_user_full(db_session, plan: str, email: str):
    """Create an org + admin user and return (headers, user, org)."""
    org = Organization(name=f"Org {email}", slug=f"org-{email[:8]}", plan=plan)
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
    return {"Authorization": "Bearer " + token}, user, org


@pytest.mark.asyncio
async def test_ticket_triage_gated_for_starter(client, db_session):
    headers = await _make_org_user(db_session, "starter", "triage-gate@test.com")
    resp = await client.post(
        "/api/v1/ai/tickets/triage",
        headers=headers,
        json={"subject": "Leak", "description": "Water leak"},
    )
    assert resp.status_code == 402, resp.text


@pytest.mark.asyncio
async def test_ticket_triage_maps_names_to_ids(client, db_session, monkeypatch):
    """The router must resolve the model's suggested category/vendor names back
    onto the org's ids and pass through a valid priority."""
    from app.models.maintenance_ticket import TicketCategory
    from app.models.vendor import Vendor

    headers, user, org = await _make_org_user_full(db_session, "pro", "triage-map@test.com")
    category = TicketCategory(name="Plumbing", organization_id=org.id)
    vendor = Vendor(company_name="Acme Plumbing", services="Plumbing repairs", organization_id=org.id)
    db_session.add_all([category, vendor])
    await db_session.commit()
    await db_session.refresh(category)
    await db_session.refresh(vendor)

    async def fake_triage(subject, description, *, categories, vendors):
        assert "Plumbing" in categories
        assert any(v["name"] == "Acme Plumbing" for v in vendors)
        return {
            "category": "Plumbing",
            "priority": "high",
            "vendor": "Acme Plumbing",
            "reasoning": "Active water leak.",
        }

    monkeypatch.setattr(ai_service, "triage_ticket", fake_triage)

    resp = await client.post(
        "/api/v1/ai/tickets/triage",
        headers=headers,
        json={"subject": "Burst pipe", "description": "Water everywhere"},
    )
    assert resp.status_code == 200, resp.text
    suggested = resp.json()["suggested"]
    assert suggested["category_id"] == str(category.id)
    assert suggested["category_name"] == "Plumbing"
    assert suggested["vendor_id"] == str(vendor.id)
    assert suggested["priority"] == "high"
    assert suggested["reasoning"] == "Active water leak."


@pytest.mark.asyncio
async def test_ticket_triage_drops_unknown_names_and_bad_priority(client, db_session, monkeypatch):
    """Hallucinated categories/vendors and invalid priorities are discarded."""
    headers, user, org = await _make_org_user_full(db_session, "pro", "triage-bad@test.com")

    async def fake_triage(subject, description, *, categories, vendors):
        return {
            "category": "Nonexistent",
            "priority": "urgent",  # not in low|medium|high
            "vendor": "Ghost Vendor",
            "reasoning": "x",
        }

    monkeypatch.setattr(ai_service, "triage_ticket", fake_triage)

    resp = await client.post(
        "/api/v1/ai/tickets/triage",
        headers=headers,
        json={"subject": "Thing", "description": "Stuff"},
    )
    assert resp.status_code == 200, resp.text
    suggested = resp.json()["suggested"]
    assert suggested["category_id"] is None
    assert suggested["vendor_id"] is None
    assert suggested["priority"] is None


@pytest.mark.asyncio
async def test_ticket_triage_degrades_when_unconfigured(client, db_session, monkeypatch):
    headers, user, org = await _make_org_user_full(db_session, "pro", "triage-503@test.com")

    async def fake_triage(subject, description, *, categories, vendors):
        raise ai_service.AIUnavailableError("not configured")

    monkeypatch.setattr(ai_service, "triage_ticket", fake_triage)

    resp = await client.post(
        "/api/v1/ai/tickets/triage",
        headers=headers,
        json={"subject": "Thing", "description": "Stuff"},
    )
    assert resp.status_code == 503, resp.text


async def _make_ticket(db_session, org, user, *, subject, description, category_id, office_id):
    from app.models.maintenance_ticket import MaintenanceTicket

    ticket = MaintenanceTicket(
        organization_id=org.id,
        subject=subject,
        priority="medium",
        status="open",
        category_id=category_id,
        office_id=office_id,
        description=description,
        created_by_id=user.id,
    )
    db_session.add(ticket)
    await db_session.commit()
    await db_session.refresh(ticket)
    return ticket


@pytest.mark.asyncio
async def test_similar_tickets_keyword_fallback(client, db_session, monkeypatch):
    """With no API key, duplicate detection falls back to keyword matching."""
    from app.models.maintenance_ticket import TicketCategory
    from app.models.office import Office

    headers, user, org = await _make_org_user_full(db_session, "pro", "similar-kw@test.com")
    category = TicketCategory(name="HVAC", organization_id=org.id)
    office = Office(office_number=1, location_type="office", location_name="HQ", organization_id=org.id)
    db_session.add_all([category, office])
    await db_session.commit()
    await db_session.refresh(category)
    await db_session.refresh(office)

    await _make_ticket(
        db_session, org, user,
        subject="Air conditioning broken in lobby",
        description="The lobby AC unit stopped cooling",
        category_id=category.id, office_id=office.id,
    )
    await _make_ticket(
        db_session, org, user,
        subject="Parking lot lights out",
        description="Several lamps in the parking lot are dark",
        category_id=category.id, office_id=office.id,
    )

    monkeypatch.setattr(ai_service, "is_configured", lambda: False)

    resp = await client.post(
        "/api/v1/ai/tickets/similar",
        headers=headers,
        json={"subject": "Lobby air conditioning not cooling", "description": "AC broken"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "keyword"
    subjects = [m["subject"] for m in body["matches"]]
    assert "Air conditioning broken in lobby" in subjects
    assert "Parking lot lights out" not in subjects


@pytest.mark.asyncio
async def test_similar_tickets_semantic_with_embeddings(client, db_session, monkeypatch):
    from app.models.maintenance_ticket import TicketCategory
    from app.models.office import Office

    headers, user, org = await _make_org_user_full(db_session, "pro", "similar-sem@test.com")
    category = TicketCategory(name="HVAC", organization_id=org.id)
    office = Office(office_number=2, location_type="office", location_name="HQ2", organization_id=org.id)
    db_session.add_all([category, office])
    await db_session.commit()
    await db_session.refresh(category)
    await db_session.refresh(office)

    dup = await _make_ticket(
        db_session, org, user,
        subject="AC down", description="cooling failure",
        category_id=category.id, office_id=office.id,
    )
    await _make_ticket(
        db_session, org, user,
        subject="Repaint hallway", description="walls scuffed",
        category_id=category.id, office_id=office.id,
    )

    monkeypatch.setattr(ai_service, "is_configured", lambda: True)

    async def fake_embed(texts):
        # First text is the query. Return a vector close to the duplicate and
        # orthogonal to the unrelated ticket.
        vecs = []
        for t in texts:
            if "AC" in t or "cooling" in t:
                vecs.append([1.0, 0.0])
            else:
                vecs.append([0.0, 1.0])
        return vecs

    monkeypatch.setattr(ai_service, "embed_texts", fake_embed)

    resp = await client.post(
        "/api/v1/ai/tickets/similar",
        headers=headers,
        json={"subject": "AC cooling broken", "description": "no cold air"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "semantic"
    ids = [m["id"] for m in body["matches"]]
    assert str(dup.id) in ids
    assert len(body["matches"]) == 1


@pytest.mark.asyncio
async def test_draft_ticket_from_email(client, db_session, monkeypatch):
    headers, user, org = await _make_org_user_full(db_session, "pro", "draft-email@test.com")

    async def fake_draft(email_text, *, categories):
        assert "leaking" in email_text
        return {"subject": "Roof leak", "priority": "high", "category": None}

    monkeypatch.setattr(ai_service, "draft_ticket_from_email", fake_draft)

    resp = await client.post(
        "/api/v1/ai/tickets/draft-from-email",
        headers=headers,
        json={"email_text": "Hi, the roof is leaking over the server room."},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["suggested"]["subject"] == "Roof leak"


@pytest.mark.asyncio
async def test_draft_ticket_from_email_gated_for_starter(client, db_session):
    headers = await _make_org_user(db_session, "starter", "draft-gate@test.com")
    resp = await client.post(
        "/api/v1/ai/tickets/draft-from-email",
        headers=headers,
        json={"email_text": "something broke"},
    )
    assert resp.status_code == 402, resp.text


@pytest.mark.asyncio
async def test_triage_ticket_service_caches(monkeypatch):
    """Identical triage inputs are served from the in-process cache."""
    ai_service.clear_parse_cache()
    calls = {"n": 0}

    async def fake_generate(parts, **kwargs):
        calls["n"] += 1
        return '{"category": "Plumbing", "priority": "high", "vendor": null, "reasoning": "x"}'

    monkeypatch.setattr(ai_service, "_generate", fake_generate)

    args = dict(categories=["Plumbing"], vendors=[{"name": "Acme", "services": "pipes"}])
    first = await ai_service.triage_ticket("Leak", "Pipe burst", **args)
    second = await ai_service.triage_ticket("Leak", "Pipe burst", **args)
    assert first == second
    assert calls["n"] == 1
    ai_service.clear_parse_cache()


# ── Phase 3: portfolio assistant (RAG Q&A) ────────────────────────────────────

@pytest.mark.asyncio
async def test_assistant_query_gated_for_starter(client, db_session):
    headers = await _make_org_user(db_session, "starter", "assist-gate@test.com")
    resp = await client.post(
        "/api/v1/ai/assistant/query",
        headers=headers,
        json={"question": "When does my downtown lease expire?"},
    )
    assert resp.status_code == 402, resp.text


@pytest.mark.asyncio
async def test_assistant_query_returns_answer_with_citations(client, db_session, monkeypatch):
    """A Pro org gets a grounded answer plus citations mapped from retrieval."""
    from app.services import knowledge_service

    headers, user, org = await _make_org_user_full(db_session, "pro", "assist-ok@test.com")

    async def fake_retrieve(db, *, organization_id, query, limit=8):
        assert organization_id == org.id
        return [
            {
                "source_type": "lease",
                "source_id": "11111111-1111-1111-1111-111111111111",
                "title": "Lease: Downtown HQ",
                "reference": "leases/11111111-1111-1111-1111-111111111111",
                "content": "Lease: Downtown HQ. Expiration: 2027-05-31.",
                "score": 0.91,
                "match_type": "semantic",
            }
        ]

    captured = {}

    async def fake_answer(question, context_blocks):
        captured["question"] = question
        captured["n_blocks"] = len(context_blocks)
        return "Your Downtown HQ lease expires on 2027-05-31 [1]."

    monkeypatch.setattr(knowledge_service, "retrieve", fake_retrieve)
    monkeypatch.setattr(ai_service, "answer_assistant_question", fake_answer)

    resp = await client.post(
        "/api/v1/ai/assistant/query",
        headers=headers,
        json={"question": "When does my Downtown HQ lease expire?"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "2027-05-31" in body["answer"]
    assert "2027-05-31" in body["answer_html"]
    assert body["answer_html"].strip().startswith("<")
    assert body["mode"] == "semantic"
    assert len(body["citations"]) == 1
    citation = body["citations"][0]
    assert citation["index"] == 1
    assert citation["source_type"] == "lease"
    assert citation["title"] == "Lease: Downtown HQ"
    assert captured["n_blocks"] == 1


@pytest.mark.asyncio
async def test_assistant_query_degrades_when_unconfigured(client, db_session, monkeypatch):
    """When Gemini is unconfigured the answer step raises → 503."""
    from app.services import knowledge_service

    headers, user, org = await _make_org_user_full(db_session, "pro", "assist-503@test.com")

    async def fake_retrieve(db, *, organization_id, query, limit=8):
        return []

    async def fake_answer(question, context_blocks):
        raise ai_service.AIUnavailableError("AI assist is not configured")

    monkeypatch.setattr(knowledge_service, "retrieve", fake_retrieve)
    monkeypatch.setattr(ai_service, "answer_assistant_question", fake_answer)

    resp = await client.post(
        "/api/v1/ai/assistant/query",
        headers=headers,
        json={"question": "Anything?"},
    )
    assert resp.status_code == 503, resp.text


@pytest.mark.asyncio
async def test_assistant_reindex_builds_and_keyword_retrieves(client, db_session):
    """Reindex builds keyword-only chunks (AI off) that keyword retrieval finds."""
    from sqlalchemy import select

    from app.models.knowledge_chunk import KnowledgeChunk
    from app.models.lease import Lease
    from app.services import knowledge_service

    headers, user, org = await _make_org_user_full(db_session, "pro", "assist-reindex@test.com")
    lease = Lease(
        lease_name="Riverside Distribution Center",
        expiration_year=2030,
        organization_id=org.id,
    )
    db_session.add(lease)
    await db_session.commit()

    resp = await client.post("/api/v1/ai/assistant/reindex", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["indexed"] >= 1

    rows = (
        await db_session.execute(
            select(KnowledgeChunk).where(KnowledgeChunk.organization_id == org.id)
        )
    ).scalars().all()
    assert any("Riverside Distribution Center" in r.content for r in rows)

    matches = await knowledge_service.retrieve(
        db_session, organization_id=org.id, query="Riverside Distribution", limit=5
    )
    assert matches
    assert any("Riverside" in m["content"] for m in matches)
    assert matches[0]["match_type"] == "keyword"


@pytest.mark.asyncio
async def test_assistant_index_covers_whole_portfolio(client, db_session):
    """The knowledge index spans offices, landlords and vendors, not just leases.

    Regression for the assistant only being able to answer questions about a few
    topics (leases/tickets/abstracts): a question like "how many offices" must
    now find office, landlord and vendor records.
    """
    from app.models.knowledge_chunk import (
        SOURCE_LANDLORD,
        SOURCE_OFFICE,
        SOURCE_VENDOR,
    )
    from app.models.landlord import Landlord
    from app.models.office import Office
    from app.models.vendor import Vendor
    from app.services import knowledge_service

    headers, user, org = await _make_org_user_full(
        db_session, "pro", "assist-portfolio@test.com"
    )
    db_session.add(
        Office(
            office_number=42,
            location_type="branch",
            location_name="Galaxy Tower Office",
            organization_id=org.id,
        )
    )
    db_session.add(
        Landlord(
            landlord_company="Orbit Realty Holdings",
            organization_id=org.id,
        )
    )
    db_session.add(
        Vendor(
            company_name="Nebula Plumbing Services",
            services="Plumbing",
            organization_id=org.id,
        )
    )
    await db_session.commit()

    resp = await client.post("/api/v1/ai/assistant/reindex", headers=headers)
    assert resp.status_code == 200, resp.text

    office_matches = await knowledge_service.retrieve(
        db_session, organization_id=org.id, query="Galaxy Tower Office", limit=5
    )
    assert any(m["source_type"] == SOURCE_OFFICE for m in office_matches)

    landlord_matches = await knowledge_service.retrieve(
        db_session, organization_id=org.id, query="Orbit Realty Holdings", limit=5
    )
    assert any(m["source_type"] == SOURCE_LANDLORD for m in landlord_matches)

    vendor_matches = await knowledge_service.retrieve(
        db_session, organization_id=org.id, query="Nebula Plumbing", limit=5
    )
    assert any(m["source_type"] == SOURCE_VENDOR for m in vendor_matches)

@pytest.mark.asyncio
async def test_assistant_index_includes_portfolio_summary_totals(client, db_session):
    """A "how many ... in total" question retrieves an org-wide summary chunk.

    Aggregate/count questions can't be answered from the handful of individual
    record chunks retrieval returns, so the index now includes one synthetic
    portfolio-summary chunk stating the totals. It must surface (and rank first)
    for count questions so the model can answer "how many offices in total".
    """
    from app.models.knowledge_chunk import SOURCE_PORTFOLIO_SUMMARY
    from app.models.office import Office
    from app.services import knowledge_service

    headers, user, org = await _make_org_user_full(
        db_session, "pro", "assist-summary@test.com"
    )
    for n in range(3):
        db_session.add(
            Office(
                office_number=100 + n,
                location_type="branch",
                location_name=f"Summary Office {n}",
                is_active=True,
                organization_id=org.id,
            )
        )
    await db_session.commit()

    resp = await client.post("/api/v1/ai/assistant/reindex", headers=headers)
    assert resp.status_code == 200, resp.text

    matches = await knowledge_service.retrieve(
        db_session, organization_id=org.id, query="how many offices in total?", limit=5
    )
    summary = next(
        (m for m in matches if m["source_type"] == SOURCE_PORTFOLIO_SUMMARY), None
    )
    assert summary is not None
    assert "Total offices: 3" in summary["content"]
    # The summary covers every entity type, not just offices.
    for label in (
        "Total leases:",
        "Total landlords:",
        "Total vendors:",
        "Total maintenance tickets:",
        "Total HVAC contracts:",
    ):
        assert label in summary["content"]
    # The summary must rank first for an aggregate question.
    assert matches[0]["source_type"] == SOURCE_PORTFOLIO_SUMMARY
