"""Coverage tests for the expanded RAG index (residential + finance domains).

The portfolio assistant historically only indexed the legacy commercial
entities (offices, leases, vendors...). These tests assert that records from the
newer product domains — residents, rental units, property owners, budgets — are
now indexed by :func:`knowledge_service.reindex_organization`, retrievable, and
still strictly organization-scoped.
"""
import uuid

import pytest

from app.models.organization import Organization
from app.models.resident import RentalUnit, Resident
from app.models.owner import PropertyOwner
from app.models.budget import Budget
from app.models.leasing_funnel import RentalApplication
from app.services import ai_service, knowledge_service


async def _make_org(db_session, slug: str):
    org = Organization(name=f"Org {slug}", slug=slug, plan="pro")
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    return org


@pytest.mark.asyncio
async def test_new_domains_indexed_and_retrievable(db_session, monkeypatch):
    monkeypatch.setattr(ai_service, "is_configured", lambda: False)
    org = await _make_org(db_session, "cov-a")

    resident = Resident(
        organization_id=org.id, first_name="Zephyrine", last_name="Qubillsworth"
    )
    unit = RentalUnit(organization_id=org.id, unit_number="Penthouse-Zorbtastic")
    owner = PropertyOwner(
        organization_id=org.id, owner_type="individual", name="Grimswald Holdings"
    )
    budget = Budget(organization_id=org.id, name="Moonbase Operations", fiscal_year=2031)
    db_session.add_all([resident, unit, owner, budget])
    await db_session.commit()

    await knowledge_service.reindex_organization(db_session, org.id)

    cases = [
        ("Zephyrine Qubillsworth resident", "resident"),
        ("Penthouse-Zorbtastic unit", "rental_unit"),
        ("Grimswald Holdings owner", "owner"),
        ("Moonbase Operations budget", "budget"),
    ]
    for query, source_type in cases:
        results = await knowledge_service.retrieve(
            db_session, organization_id=org.id, query=query, limit=20
        )
        assert any(
            r["source_type"] == source_type for r in results
        ), f"expected a {source_type} chunk for query {query!r}"


@pytest.mark.asyncio
async def test_new_domain_chunks_are_org_scoped(db_session, monkeypatch):
    monkeypatch.setattr(ai_service, "is_configured", lambda: False)
    org_a = await _make_org(db_session, "cov-scope-a")
    org_b = await _make_org(db_session, "cov-scope-b")

    db_session.add(
        Resident(organization_id=org_a.id, first_name="Alphonse", last_name="Wobblebottom")
    )
    db_session.add(
        Resident(organization_id=org_b.id, first_name="Bartholomew", last_name="Wobblebottom")
    )
    await db_session.commit()

    await knowledge_service.reindex_organization(db_session, org_a.id)
    await knowledge_service.reindex_organization(db_session, org_b.id)

    res_a = await knowledge_service.retrieve(
        db_session, organization_id=org_a.id, query="Wobblebottom", limit=20
    )
    assert res_a
    assert all("Bartholomew" not in r["content"] for r in res_a)
    assert any("Alphonse" in r["content"] for r in res_a)


@pytest.mark.asyncio
async def test_portfolio_summary_counts_new_domains(db_session, monkeypatch):
    monkeypatch.setattr(ai_service, "is_configured", lambda: False)
    org = await _make_org(db_session, "cov-summary")
    db_session.add_all(
        [
            Resident(organization_id=org.id, first_name="Countable", last_name="One"),
            Resident(organization_id=org.id, first_name="Countable", last_name="Two"),
        ]
    )
    await db_session.commit()

    await knowledge_service.reindex_organization(db_session, org.id)

    results = await knowledge_service.retrieve(
        db_session, organization_id=org.id, query="total residents portfolio", limit=20
    )
    summary = next(
        (r for r in results if r["source_type"] == "portfolio_summary"), None
    )
    assert summary is not None
    assert "Total residents: 2" in summary["content"]

@pytest.mark.asyncio
async def test_rental_applications_indexed_and_retrievable(db_session, monkeypatch):
    """Regression: applications must be indexed so the assistant can answer
    questions like "do I have any open residential applications" instead of
    falling back to unrelated lease-document chunks."""
    monkeypatch.setattr(ai_service, "is_configured", lambda: False)
    org = await _make_org(db_session, "cov-apps")

    db_session.add_all(
        [
            RentalApplication(
                organization_id=org.id,
                applicant_first_name="Zorbtron",
                applicant_last_name="Applicanthanks",
                applicant_email="zorbtron@example.com",
                status="screening",
            ),
            RentalApplication(
                organization_id=org.id,
                applicant_first_name="Quibbly",
                applicant_last_name="Screenerson",
                applicant_email="quibbly@example.com",
                status="screening",
            ),
        ]
    )
    await db_session.commit()

    await knowledge_service.reindex_organization(db_session, org.id)

    results = await knowledge_service.retrieve(
        db_session,
        organization_id=org.id,
        query="rental applications in screening",
        limit=20,
    )
    assert any(r["source_type"] == "rental_application" for r in results)

    summary = next(
        (r for r in results if r["source_type"] == "portfolio_summary"), None
    )
    assert summary is not None
    assert "Total rental applications: 2" in summary["content"]
    assert "applications in screening: 2" in summary["content"]


@pytest.mark.asyncio
async def test_open_residential_applications_answerable(db_session, monkeypatch):
    """Regression for the screenshot: a query using the word "residential" and
    asking for "open" applications must surface the portfolio summary with an
    explicit open-applications count and the residential synonym."""
    monkeypatch.setattr(ai_service, "is_configured", lambda: False)
    org = await _make_org(db_session, "cov-open-apps")

    db_session.add_all(
        [
            # Two open/in-progress applications (non-terminal statuses).
            RentalApplication(
                organization_id=org.id,
                applicant_first_name="Opennly",
                applicant_last_name="Pending",
                applicant_email="openly@example.com",
                status="screening",
            ),
            RentalApplication(
                organization_id=org.id,
                applicant_first_name="Stilly",
                applicant_last_name="Reviewing",
                applicant_email="stilly@example.com",
                status="in_review",
            ),
            # One closed/decided application (terminal status) — not "open".
            RentalApplication(
                organization_id=org.id,
                applicant_first_name="Donely",
                applicant_last_name="Approved",
                applicant_email="donely@example.com",
                status="approved",
            ),
        ]
    )
    await db_session.commit()

    await knowledge_service.reindex_organization(db_session, org.id)

    results = await knowledge_service.retrieve(
        db_session,
        organization_id=org.id,
        query="how many open residential applications are there",
        limit=20,
    )
    summary = next(
        (r for r in results if r["source_type"] == "portfolio_summary"), None
    )
    assert summary is not None
    assert "Total rental applications: 3" in summary["content"]
    assert "open residential applications: 2" in summary["content"]
    assert "residential applications" in summary["content"]
