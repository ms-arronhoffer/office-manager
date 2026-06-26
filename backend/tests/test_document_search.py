"""Tests for lease document search (keyword + semantic)."""
import uuid

import pytest

from app.auth.jwt_handler import create_access_token
from app.auth.password import hash_password
from app.models.attachment import Attachment
from app.models.lease import Lease
from app.models.lease_document_chunk import LeaseDocumentChunk
from app.models.organization import Organization
from app.models.user import User
from app.services import ai_service, document_search_service


async def _make_org_user(db_session, email: str):
    org = Organization(name="DS Org", slug=f"ds-{email[:6]}", plan="pro")
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
    return org, user, {"Authorization": "Bearer " + token}


async def _make_lease(db_session, org, name="Acme HQ Lease"):
    lease = Lease(lease_name=name, organization_id=org.id, expiration_year=2030)
    db_session.add(lease)
    await db_session.commit()
    await db_session.refresh(lease)
    return lease


# ── Unit: chunking + similarity ───────────────────────────────────────────────

def test_chunk_text_splits_and_overlaps():
    text = "word " * 1000  # 5000 chars
    chunks = document_search_service.chunk_text(text)
    assert len(chunks) > 1
    assert all(c.strip() for c in chunks)


def test_chunk_text_empty():
    assert document_search_service.chunk_text("") == []
    assert document_search_service.chunk_text("   ") == []


def test_cosine_similarity():
    assert document_search_service._cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert document_search_service._cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert document_search_service._cosine([], [1, 2]) == 0.0


# ── Keyword fallback (no Gemini) ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_keyword_search_when_ai_unconfigured(db_session, monkeypatch):
    monkeypatch.setattr(ai_service, "is_configured", lambda: False)
    org, user, _ = await _make_org_user(db_session, "kw@test.com")
    lease = await _make_lease(db_session, org)

    db_session.add(
        LeaseDocumentChunk(
            organization_id=org.id,
            lease_id=lease.id,
            attachment_id=None,
            source_filename="lease.pdf",
            chunk_index=0,
            content="The tenant shall pay base rent of $5,000 per month for the premises.",
            embedding=None,
        )
    )
    await db_session.commit()

    results = await document_search_service.search_documents(
        db_session, organization_id=org.id, query="base rent"
    )
    assert len(results) == 1
    assert results[0]["lease_id"] == str(lease.id)
    assert results[0]["match_type"] == "keyword"
    assert "base rent" in results[0]["snippet"].lower()


@pytest.mark.asyncio
async def test_keyword_search_is_org_scoped(db_session, monkeypatch):
    monkeypatch.setattr(ai_service, "is_configured", lambda: False)
    org_a, _, _ = await _make_org_user(db_session, "orga@test.com")
    org_b, _, _ = await _make_org_user(db_session, "orgb@test.com")
    lease_a = await _make_lease(db_session, org_a, "A Lease")
    lease_b = await _make_lease(db_session, org_b, "B Lease")
    for org, lease in ((org_a, lease_a), (org_b, lease_b)):
        db_session.add(
            LeaseDocumentChunk(
                organization_id=org.id,
                lease_id=lease.id,
                source_filename="x.pdf",
                chunk_index=0,
                content="confidential indemnification clause",
            )
        )
    await db_session.commit()

    results = await document_search_service.search_documents(
        db_session, organization_id=org_a.id, query="indemnification"
    )
    assert len(results) == 1
    assert results[0]["lease_id"] == str(lease_a.id)


# ── Semantic ranking (mocked embeddings) ──────────────────────────────────────

@pytest.mark.asyncio
async def test_semantic_search_ranks_by_cosine(db_session, monkeypatch):
    monkeypatch.setattr(ai_service, "is_configured", lambda: True)
    org, user, _ = await _make_org_user(db_session, "sem@test.com")
    lease1 = await _make_lease(db_session, org, "Relevant Lease")
    lease2 = await _make_lease(db_session, org, "Irrelevant Lease")

    db_session.add_all([
        LeaseDocumentChunk(
            organization_id=org.id, lease_id=lease1.id, source_filename="a.pdf",
            chunk_index=0, content="termination rights", embedding=[1.0, 0.0, 0.0],
        ),
        LeaseDocumentChunk(
            organization_id=org.id, lease_id=lease2.id, source_filename="b.pdf",
            chunk_index=0, content="parking provisions", embedding=[0.0, 1.0, 0.0],
        ),
    ])
    await db_session.commit()

    async def fake_embed(texts):
        # Query embedding aligned with lease1's chunk vector.
        return [[1.0, 0.0, 0.0] for _ in texts]

    monkeypatch.setattr(ai_service, "embed_texts", fake_embed)

    results = await document_search_service.search_documents(
        db_session, organization_id=org.id, query="how can the lease be terminated"
    )
    assert results
    assert results[0]["lease_id"] == str(lease1.id)
    assert results[0]["match_type"] == "semantic"
    assert results[0]["score"] == pytest.approx(1.0, abs=1e-3)


# ── Endpoint ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_document_search_endpoint(client, db_session, monkeypatch):
    monkeypatch.setattr(ai_service, "is_configured", lambda: False)
    org, user, headers = await _make_org_user(db_session, "ep@test.com")
    lease = await _make_lease(db_session, org)
    db_session.add(
        LeaseDocumentChunk(
            organization_id=org.id, lease_id=lease.id, source_filename="lease.pdf",
            chunk_index=0, content="renewal option exercisable with 180 days notice",
        )
    )
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/leases/{lease.id}/document-search",
        headers=headers,
        json={"query": "renewal option"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["matches"]
    assert body["matches"][0]["lease_id"] == str(lease.id)


@pytest.mark.asyncio
async def test_index_attachment_keyword_only(db_session, monkeypatch):
    """index_attachment stores chunks even when AI is off (keyword-only)."""
    import io

    import docx

    monkeypatch.setattr(ai_service, "is_configured", lambda: False)
    org, user, _ = await _make_org_user(db_session, "idx@test.com")
    lease = await _make_lease(db_session, org)

    document = docx.Document()
    document.add_paragraph("Assignment and subletting require landlord consent.")
    buf = io.BytesIO()
    document.save(buf)

    attachment = Attachment(
        organization_id=org.id,
        entity_type="lease",
        entity_id=lease.id,
        original_filename="lease.docx",
        stored_filename=f"{uuid.uuid4()}.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size=buf.tell(),
        uploaded_by=user.email,
    )
    db_session.add(attachment)
    await db_session.commit()
    await db_session.refresh(attachment)

    count = await document_search_service.index_attachment(
        db_session, lease=lease, attachment=attachment, content=buf.getvalue()
    )
    assert count == 1

    results = await document_search_service.search_documents(
        db_session, organization_id=org.id, query="subletting"
    )
    assert results and results[0]["lease_id"] == str(lease.id)
