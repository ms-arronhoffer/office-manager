"""Coverage for the generic catch-all knowledge indexer.

The bespoke builders in :mod:`app.services.knowledge_service` only cover a
subset of the schema. The generic indexer additionally reflects over *every*
organization-scoped table so the assistant can answer questions about any data
in the database. These tests assert that generically-indexed records are
retrievable, strictly org-scoped, counted in the portfolio summary, and that
sensitive columns (tokens, hashes) are never embedded.
"""
import uuid

import pytest

from app.models.organization import Organization
from app.models.office import Manager
from app.models.waiver import WaiverRequest
from app.services import ai_service, knowledge_service


async def _make_org(db_session, slug: str):
    org = Organization(name=f"Org {slug}", slug=slug, plan="pro")
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    return org


@pytest.mark.asyncio
async def test_generic_table_indexed_and_retrievable(db_session, monkeypatch):
    """A model with no bespoke builder (managers) is still indexed."""
    monkeypatch.setattr(ai_service, "is_configured", lambda: False)
    org = await _make_org(db_session, "gen-a")

    db_session.add(
        Manager(
            organization_id=org.id,
            name="Wilhelmina Snorgtackle",
            email="wilhelmina@example.com",
        )
    )
    await db_session.commit()

    await knowledge_service.reindex_organization(db_session, org.id)

    results = await knowledge_service.retrieve(
        db_session, organization_id=org.id, query="Wilhelmina Snorgtackle manager", limit=20
    )
    assert any(r["source_type"] == "managers" for r in results)
    assert any("Wilhelmina Snorgtackle" in r["content"] for r in results)


@pytest.mark.asyncio
async def test_generic_chunks_are_org_scoped(db_session, monkeypatch):
    monkeypatch.setattr(ai_service, "is_configured", lambda: False)
    org_a = await _make_org(db_session, "gen-scope-a")
    org_b = await _make_org(db_session, "gen-scope-b")

    db_session.add(Manager(organization_id=org_a.id, name="Alphaman Zizzlebop"))
    db_session.add(Manager(organization_id=org_b.id, name="Betaman Zizzlebop"))
    await db_session.commit()

    await knowledge_service.reindex_organization(db_session, org_a.id)
    await knowledge_service.reindex_organization(db_session, org_b.id)

    res_a = await knowledge_service.retrieve(
        db_session, organization_id=org_a.id, query="Zizzlebop", limit=20
    )
    assert res_a
    assert all("Betaman" not in r["content"] for r in res_a)
    assert any("Alphaman" in r["content"] for r in res_a)


@pytest.mark.asyncio
async def test_generic_indexer_redacts_sensitive_columns(db_session, monkeypatch):
    monkeypatch.setattr(ai_service, "is_configured", lambda: False)
    org = await _make_org(db_session, "gen-redact")

    db_session.add(
        WaiverRequest(
            organization_id=org.id,
            recipient_type="visitor",
            recipient_name="Gwendolyn Fizzlewhistle",
            recipient_email="gwendolyn@example.com",
            title="Pool Liability Waiver",
            rendered_body="I hereby waive all claims.",
            document_hash="TOPSECRETHASH1234567890",
            sign_token="SUPERSECRETSIGNTOKEN9999",
        )
    )
    await db_session.commit()

    await knowledge_service.reindex_organization(db_session, org.id)

    results = await knowledge_service.retrieve(
        db_session, organization_id=org.id, query="Pool Liability Waiver Fizzlewhistle", limit=20
    )
    waiver_chunks = [r for r in results if r["source_type"] == "waiver_requests"]
    assert waiver_chunks, "waiver request should be generically indexed"
    joined = " ".join(r["content"] for r in waiver_chunks)
    assert "Pool Liability Waiver" in joined
    # Secrets must never be embedded/returned.
    assert "SUPERSECRETSIGNTOKEN9999" not in joined
    assert "TOPSECRETHASH1234567890" not in joined


@pytest.mark.asyncio
async def test_portfolio_summary_counts_generic_tables(db_session, monkeypatch):
    monkeypatch.setattr(ai_service, "is_configured", lambda: False)
    org = await _make_org(db_session, "gen-summary")
    db_session.add_all(
        [
            Manager(organization_id=org.id, name="Counter One"),
            Manager(organization_id=org.id, name="Counter Two"),
        ]
    )
    await db_session.commit()

    await knowledge_service.reindex_organization(db_session, org.id)

    results = await knowledge_service.retrieve(
        db_session, organization_id=org.id, query="total managers portfolio", limit=20
    )
    summary = next(
        (r for r in results if r["source_type"] == "portfolio_summary"), None
    )
    assert summary is not None
    assert "Total managers: 2" in summary["content"]
