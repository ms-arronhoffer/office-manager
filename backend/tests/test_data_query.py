"""Tests for the structured data-query engine (:mod:`app.services.data_query_service`).

Covers the catalog allow-list (sensitive tables/columns excluded), spec
validation (rejecting unknown entities/columns/operators/aggregates), executor
correctness (filters, counts, sums, group-by, ordering, limits), and — most
importantly — strict organization isolation.
"""
import uuid

import pytest

from app.models.organization import Organization
from app.models.office import Manager
from app.models.leasing_funnel import RentalApplication
from app.services import data_query_service as dq


async def _make_org(db_session, slug: str) -> Organization:
    org = Organization(name=f"Org {slug}", slug=slug, plan="pro")
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    return org


# ── Catalog ───────────────────────────────────────────────────────────────────

def test_catalog_covers_business_tables_and_excludes_sensitive():
    catalog = dq.build_catalog()
    # Core business tables are queryable.
    assert "offices" in catalog
    assert "leases" in catalog
    assert "rental_applications" in catalog
    # Sensitive / credential / metering tables are never exposed.
    assert "users" not in catalog
    assert "api_keys" not in catalog
    assert "knowledge_chunks" not in catalog
    assert "billing_subscriptions" not in catalog
    # organization_id is never a queryable column (the engine scopes itself).
    for cfg in catalog.values():
        assert "organization_id" not in cfg["columns"]


def test_catalog_drops_sensitive_columns():
    catalog = dq.build_catalog()
    for entity, cfg in catalog.items():
        for name in cfg["columns"]:
            lowered = name.lower()
            for frag in ("password", "secret", "token", "hash", "api_key"):
                assert frag not in lowered, f"{entity}.{name} leaked a sensitive column"


def test_catalog_for_prompt_is_model_free():
    entities = dq.catalog_for_prompt()
    assert entities
    sample = entities[0]
    assert set(sample.keys()) == {"entity", "title", "columns"}
    col = sample["columns"][0]
    assert set(col.keys()) == {"name", "label", "kind"}


# ── Spec validation ───────────────────────────────────────────────────────────

def test_validate_rejects_unknown_entity():
    with pytest.raises(dq.DataQueryError):
        dq.validate_spec({"entity": "not_a_table"})


def test_validate_rejects_unknown_column():
    with pytest.raises(dq.DataQueryError):
        dq.validate_spec({"entity": "offices", "select": ["nonexistent_col"]})


def test_validate_rejects_unknown_operator():
    with pytest.raises(dq.DataQueryError):
        dq.validate_spec({
            "entity": "offices",
            "filters": [{"column": "city", "op": "regex", "value": "x"}],
        })


def test_validate_rejects_unknown_aggregate():
    with pytest.raises(dq.DataQueryError):
        dq.validate_spec({"entity": "offices", "aggregate": "median"})


def test_validate_requires_numeric_column_for_sum():
    with pytest.raises(dq.DataQueryError):
        dq.validate_spec({
            "entity": "offices",
            "aggregate": "sum",
            "aggregate_column": "city",  # text column
        })


def test_validate_group_by_requires_aggregate():
    with pytest.raises(dq.DataQueryError):
        dq.validate_spec({"entity": "offices", "group_by": ["state"]})


def test_validate_caps_limit():
    spec = dq.validate_spec({"entity": "offices", "limit": 10_000})
    assert spec["limit"] == dq.MAX_LIMIT


def test_validate_coerces_filter_values():
    spec = dq.validate_spec({
        "entity": "rental_applications",
        "filters": [{"column": "status", "op": "eq", "value": "screening"}],
    })
    assert spec["filters"][0]["value"] == "screening"


def test_validate_rejects_bad_value_type():
    # monthly_income is numeric; a non-numeric value must be rejected.
    with pytest.raises(dq.DataQueryError):
        dq.validate_spec({
            "entity": "rental_applications",
            "filters": [
                {"column": "monthly_income", "op": "gt", "value": "not-a-number"}
            ],
        })


# ── Executor ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_count_with_filter(db_session):
    org = await _make_org(db_session, "dq-count")
    db_session.add_all([
        RentalApplication(
            organization_id=org.id, applicant_first_name="A",
            applicant_last_name="One", applicant_email="a@example.com",
            status="screening",
        ),
        RentalApplication(
            organization_id=org.id, applicant_first_name="B",
            applicant_last_name="Two", applicant_email="b@example.com",
            status="screening",
        ),
        RentalApplication(
            organization_id=org.id, applicant_first_name="C",
            applicant_last_name="Three", applicant_email="c@example.com",
            status="approved",
        ),
    ])
    await db_session.commit()

    spec = dq.validate_spec({
        "entity": "rental_applications",
        "aggregate": "count",
        "filters": [{"column": "status", "op": "eq", "value": "screening"}],
    })
    result = await dq.execute_spec(db_session, organization_id=org.id, spec=spec)
    assert result["rows"] == [[2]]
    assert "count" in result["columns"][0]


@pytest.mark.asyncio
async def test_execute_group_by(db_session):
    org = await _make_org(db_session, "dq-group")
    db_session.add_all([
        RentalApplication(organization_id=org.id, applicant_first_name="A",
                          applicant_last_name="x", applicant_email="a@e.com",
                          status="screening"),
        RentalApplication(organization_id=org.id, applicant_first_name="B",
                          applicant_last_name="x", applicant_email="b@e.com",
                          status="screening"),
        RentalApplication(organization_id=org.id, applicant_first_name="C",
                          applicant_last_name="x", applicant_email="c@e.com",
                          status="approved"),
    ])
    await db_session.commit()

    spec = dq.validate_spec({
        "entity": "rental_applications",
        "aggregate": "count",
        "group_by": ["status"],
    })
    result = await dq.execute_spec(db_session, organization_id=org.id, spec=spec)
    grouped = {row[0]: row[1] for row in result["rows"]}
    assert grouped == {"screening": 2, "approved": 1}


@pytest.mark.asyncio
async def test_execute_rows_with_select_and_order(db_session):
    org = await _make_org(db_session, "dq-rows")
    db_session.add_all([
        Manager(organization_id=org.id, name="Zed", email="z@example.com"),
        Manager(organization_id=org.id, name="Abe", email="a@example.com"),
    ])
    await db_session.commit()

    spec = dq.validate_spec({
        "entity": "managers",
        "select": ["name", "email"],
        "order_by": {"column": "name", "direction": "asc"},
    })
    result = await dq.execute_spec(db_session, organization_id=org.id, spec=spec)
    assert result["columns"] == ["name", "email"]
    names = [row[0] for row in result["rows"]]
    assert names == ["Abe", "Zed"]
    assert result["total"] == 2


@pytest.mark.asyncio
async def test_execute_contains_filter(db_session):
    org = await _make_org(db_session, "dq-contains")
    db_session.add_all([
        Manager(organization_id=org.id, name="Wilhelmina Snorgtackle"),
        Manager(organization_id=org.id, name="Bob Smith"),
    ])
    await db_session.commit()

    spec = dq.validate_spec({
        "entity": "managers",
        "select": ["name"],
        "filters": [{"column": "name", "op": "contains", "value": "snorg"}],
    })
    result = await dq.execute_spec(db_session, organization_id=org.id, spec=spec)
    assert result["total"] == 1
    assert result["rows"][0][0] == "Wilhelmina Snorgtackle"


@pytest.mark.asyncio
async def test_execute_is_strictly_org_scoped(db_session):
    """A query for org A must never see org B's rows even without a filter."""
    org_a = await _make_org(db_session, "dq-iso-a")
    org_b = await _make_org(db_session, "dq-iso-b")
    db_session.add_all([
        Manager(organization_id=org_a.id, name="Alpha One"),
        Manager(organization_id=org_a.id, name="Alpha Two"),
        Manager(organization_id=org_b.id, name="Beta One"),
    ])
    await db_session.commit()

    spec = dq.validate_spec({"entity": "managers", "aggregate": "count"})
    result_a = await dq.execute_spec(db_session, organization_id=org_a.id, spec=spec)
    result_b = await dq.execute_spec(db_session, organization_id=org_b.id, spec=spec)
    assert result_a["rows"] == [[2]]
    assert result_b["rows"] == [[1]]

    # Row query is scoped too.
    row_spec = dq.validate_spec({"entity": "managers", "select": ["name"]})
    rows_a = await dq.execute_spec(db_session, organization_id=org_a.id, spec=row_spec)
    names_a = {r[0] for r in rows_a["rows"]}
    assert names_a == {"Alpha One", "Alpha Two"}
    assert "Beta One" not in names_a


@pytest.mark.asyncio
async def test_execute_limit_truncates_but_reports_total(db_session):
    org = await _make_org(db_session, "dq-limit")
    for i in range(5):
        db_session.add(Manager(organization_id=org.id, name=f"M{i}"))
    await db_session.commit()

    spec = dq.validate_spec({"entity": "managers", "select": ["name"], "limit": 2})
    result = await dq.execute_spec(db_session, organization_id=org.id, spec=spec)
    assert len(result["rows"]) == 2
    assert result["total"] == 5


def test_summarize_count():
    spec = dq.validate_spec({"entity": "managers", "aggregate": "count"})
    text = dq.summarize(spec, {"columns": ["count"], "rows": [[7]], "total": 1})
    assert "7" in text


# ── AI translation layer ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_data_query_spec_passes_catalog_and_parses(monkeypatch):
    """build_data_query_spec sends the catalog and returns the parsed JSON."""
    from app.services import ai_service

    captured = {}

    async def fake_generate(parts, **kwargs):
        captured["prompt"] = parts[0]["text"]
        captured["model"] = kwargs.get("model")
        return '{"entity": "managers", "aggregate": "count"}'

    monkeypatch.setattr(ai_service, "_generate", fake_generate)

    entities = dq.catalog_for_prompt()
    spec = await ai_service.build_data_query_spec("how many managers", entities)
    assert spec == {"entity": "managers", "aggregate": "count"}
    # The prompt must enumerate real entities and use the cheap "fast" model.
    assert "managers" in captured["prompt"]
    assert captured["model"] == "fast"


@pytest.mark.asyncio
async def test_build_data_query_spec_requires_question(monkeypatch):
    from app.services import ai_service

    with pytest.raises(ai_service.AIRequestError):
        await ai_service.build_data_query_spec("   ", dq.catalog_for_prompt())
