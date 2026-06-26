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
