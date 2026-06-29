"""Cross-organization isolation + generalized-document tests for the RAG corpus.

These assert the "no overlap / no data intrusion" requirement: a query for one
organization must NEVER return another organization's chunks or citations, on
both the keyword-fallback and (empty-embedding) paths. They also cover Phase 2:
attachments on any entity (not just leases) are indexed and retrievable, and the
retrieval/index APIs refuse to run without an organization.
"""
import io
import uuid

import docx
import pytest

from app.auth.password import hash_password
from app.models.organization import Organization
from app.models.user import User
from app.models.vendor import Vendor
from app.models.attachment import Attachment
from app.models.lease import Lease
from app.models.knowledge_chunk import KnowledgeChunk
from app.services import ai_service, document_search_service, knowledge_service


async def _make_org(db_session, slug: str):
    org = Organization(name=f"Org {slug}", slug=slug, plan="pro")
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    return org


def _docx_bytes(text: str) -> bytes:
    document = docx.Document()
    document.add_paragraph(text)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_retrieve_strictly_scoped_to_org(db_session, monkeypatch):
    """Two orgs with overlapping content: each retrieves only its own chunks."""
    monkeypatch.setattr(ai_service, "is_configured", lambda: False)
    org_a = await _make_org(db_session, "iso-a")
    org_b = await _make_org(db_session, "iso-b")

    lease_a = Lease(lease_name="Riverside Tower", organization_id=org_a.id, expiration_year=2030)
    lease_b = Lease(lease_name="Riverside Annex", organization_id=org_b.id, expiration_year=2031)
    db_session.add_all([lease_a, lease_b])
    await db_session.commit()

    await knowledge_service.reindex_organization(db_session, org_a.id)
    await knowledge_service.reindex_organization(db_session, org_b.id)

    res_a = await knowledge_service.retrieve(
        db_session, organization_id=org_a.id, query="Riverside", limit=10
    )
    assert res_a
    assert all("Annex" not in r["content"] for r in res_a)
    assert any("Tower" in r["content"] for r in res_a)

    res_b = await knowledge_service.retrieve(
        db_session, organization_id=org_b.id, query="Riverside", limit=10
    )
    assert res_b
    assert all("Tower" not in r["content"] for r in res_b)


@pytest.mark.asyncio
async def test_retrieve_requires_org(db_session):
    with pytest.raises(ValueError):
        await knowledge_service.retrieve(db_session, organization_id=None, query="x")


@pytest.mark.asyncio
async def test_reindex_requires_org(db_session):
    with pytest.raises(ValueError):
        await knowledge_service.reindex_organization(db_session, None)


@pytest.mark.asyncio
async def test_document_index_skips_when_no_org(db_session, monkeypatch):
    """A doc with no resolvable org is never indexed (cross-org safety)."""
    monkeypatch.setattr(ai_service, "is_configured", lambda: False)
    attachment = Attachment(
        organization_id=None,
        entity_type="vendor",
        entity_id=uuid.uuid4(),
        original_filename="x.txt",
        stored_filename=f"{uuid.uuid4()}.txt",
        content_type="text/plain",
        file_size=10,
        uploaded_by="u@test.com",
    )
    db_session.add(attachment)
    await db_session.commit()
    count = await document_search_service.index_document(
        db_session,
        attachment=attachment,
        content=b"hello",
        organization_id=None,
        entity_type="vendor",
        entity_id=attachment.entity_id,
    )
    assert count == 0


@pytest.mark.asyncio
async def test_vendor_attachment_indexed_and_retrievable(db_session, monkeypatch):
    """Phase 2: a non-lease (vendor) attachment is indexed and retrieved."""
    monkeypatch.setattr(ai_service, "is_configured", lambda: False)
    org = await _make_org(db_session, "vendor-doc")
    vendor = Vendor(company_name="CoolAir HVAC", organization_id=org.id)
    db_session.add(vendor)
    await db_session.commit()
    await db_session.refresh(vendor)

    attachment = Attachment(
        organization_id=org.id,
        entity_type="vendor",
        entity_id=vendor.id,
        original_filename="contract.docx",
        stored_filename=f"{uuid.uuid4()}.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        file_size=100,
        uploaded_by="u@test.com",
    )
    db_session.add(attachment)
    await db_session.commit()
    await db_session.refresh(attachment)

    count = await document_search_service.index_document(
        db_session,
        attachment=attachment,
        content=_docx_bytes("Refrigerant maintenance scope and emergency response terms."),
        organization_id=org.id,
        entity_type="vendor",
        entity_id=vendor.id,
    )
    assert count == 1

    results = await knowledge_service.retrieve(
        db_session, organization_id=org.id, query="refrigerant maintenance", limit=5
    )
    assert results
    hit = next(r for r in results if "Refrigerant" in r["content"])
    assert hit["source_type"] == "vendor_document"
    assert hit["reference"] == f"vendor/{vendor.id}"
