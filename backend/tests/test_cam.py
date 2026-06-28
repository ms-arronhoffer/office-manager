import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lease import Lease
from app.models.operating_expense import OperatingExpense
from app.services.cam_service import compute_cam_reconciliation
from tests.conftest import auth_headers


# ─── Pure compute-engine unit tests ──────────────────────────────────────────

def _line(category, amount, controllable=True, gross_up=False):
    return {
        "category": category,
        "actual_amount": Decimal(str(amount)),
        "controllable": controllable,
        "gross_up_eligible": gross_up,
    }


def test_pro_rata_share_basic():
    result = compute_cam_reconciliation(
        lines=[_line("cam", 100000)],
        pro_rata_share=Decimal("0.10"),
        year=2025,
        estimated_paid=Decimal("8000"),
    )
    assert result["total_pool"] == Decimal("100000.00")
    assert result["tenant_share_amount"] == Decimal("10000.00")
    assert result["recoverable_amount"] == Decimal("10000.00")
    # Tenant paid 8000 in estimates, owes the 2000 true-up.
    assert result["balance_due"] == Decimal("2000.00")


def test_credit_when_overpaid():
    result = compute_cam_reconciliation(
        lines=[_line("cam", 100000)],
        pro_rata_share=Decimal("0.10"),
        year=2025,
        estimated_paid=Decimal("12000"),
    )
    # Overpaid by 2000 -> negative balance (credit owed to tenant).
    assert result["balance_due"] == Decimal("-2000.00")


def test_gross_up_applies_to_eligible_lines_only():
    result = compute_cam_reconciliation(
        lines=[
            _line("cam", 95000, gross_up=True),
            _line("taxes", 50000, controllable=False, gross_up=False),
        ],
        pro_rata_share=Decimal("0.10"),
        year=2025,
        gross_up_percent=Decimal("1.00"),
        occupancy_percent=Decimal("0.95"),
    )
    # CAM grossed 95000 -> 100000; taxes untouched at 50000.
    assert result["controllable_pool"] == Decimal("100000.00")
    assert result["noncontrollable_pool"] == Decimal("50000.00")
    assert result["total_pool"] == Decimal("150000.00")
    assert result["tenant_share_amount"] == Decimal("15000.00")


def test_no_gross_up_when_occupancy_at_or_above_standard():
    result = compute_cam_reconciliation(
        lines=[_line("cam", 100000, gross_up=True)],
        pro_rata_share=Decimal("0.10"),
        year=2025,
        gross_up_percent=Decimal("0.95"),
        occupancy_percent=Decimal("0.98"),
    )
    assert result["total_pool"] == Decimal("100000.00")


def test_controllable_cap_compounded():
    # Tenant controllable share would be 12000; cap base 10000 grown 5%/yr
    # compounded over 2 years = 11025.
    result = compute_cam_reconciliation(
        lines=[_line("cam", 120000, controllable=True)],
        pro_rata_share=Decimal("0.10"),
        year=2025,
        cap_percent=Decimal("0.05"),
        cap_type="cumulative_compounded",
        cap_base_year=2023,
        cap_base_amount=Decimal("10000"),
    )
    assert result["recoverable_amount"] == Decimal("11025.00")
    assert result["cap_applied"] == Decimal("975.00")


def test_controllable_cap_simple_cumulative():
    # 10000 * (1 + 0.05*2) = 11000.
    result = compute_cam_reconciliation(
        lines=[_line("cam", 120000, controllable=True)],
        pro_rata_share=Decimal("0.10"),
        year=2025,
        cap_percent=Decimal("0.05"),
        cap_type="cumulative",
        cap_base_year=2023,
        cap_base_amount=Decimal("10000"),
    )
    assert result["recoverable_amount"] == Decimal("11000.00")


def test_cap_does_not_limit_non_controllable():
    # Non-controllable taxes pass through uncapped even with a cap configured.
    result = compute_cam_reconciliation(
        lines=[_line("taxes", 200000, controllable=False)],
        pro_rata_share=Decimal("0.10"),
        year=2025,
        cap_percent=Decimal("0.05"),
        cap_type="cumulative_compounded",
        cap_base_year=2024,
        cap_base_amount=Decimal("1000"),
    )
    assert result["cap_applied"] == Decimal("0.00")
    assert result["recoverable_amount"] == Decimal("20000.00")


def test_expense_stop_offset():
    result = compute_cam_reconciliation(
        lines=[_line("cam", 100000)],
        pro_rata_share=Decimal("0.10"),
        year=2025,
        expense_stop_psf=Decimal("2.00"),
        rentable_sqft=Decimal("1000"),
    )
    # 10000 share minus 2.00 * 1000 = 2000 stop -> 8000.
    assert result["offset_amount"] == Decimal("2000.00")
    assert result["recoverable_amount"] == Decimal("8000.00")


def test_base_year_offset_takes_precedence_over_stop():
    result = compute_cam_reconciliation(
        lines=[_line("cam", 100000)],
        pro_rata_share=Decimal("0.10"),
        year=2025,
        base_year_amount=Decimal("3000"),
        expense_stop_psf=Decimal("2.00"),
        rentable_sqft=Decimal("1000"),
    )
    assert result["offset_amount"] == Decimal("3000.00")
    assert result["recoverable_amount"] == Decimal("7000.00")


def test_recoverable_floors_at_zero():
    result = compute_cam_reconciliation(
        lines=[_line("cam", 10000)],
        pro_rata_share=Decimal("0.10"),
        year=2025,
        base_year_amount=Decimal("5000"),
    )
    # Share 1000 minus 5000 base -> floored at 0.
    assert result["recoverable_amount"] == Decimal("0.00")


# ─── API tests ───────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def cam_lease(db_session: AsyncSession) -> Lease:
    lease = Lease(
        id=uuid.uuid4(),
        organization_id=None,
        lease_name="CAM Test Lease",
        expiration_year=2027,
        lease_commencement_date=date(2024, 1, 1),
        lease_expiration=date(2027, 1, 1),
        currency="USD",
    )
    db_session.add(lease)
    await db_session.commit()
    await db_session.refresh(lease)
    return lease


@pytest.mark.asyncio
async def test_viewer_cannot_access_cam(client, viewer_user):
    resp = await client.get(
        "/api/v1/cam/reconciliations", headers=auth_headers(viewer_user)
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_reconciliation_with_lines(client, accountant_user, cam_lease):
    headers = auth_headers(accountant_user)
    resp = await client.post(
        "/api/v1/cam/reconciliations",
        headers=headers,
        json={
            "lease_id": str(cam_lease.id),
            "year": 2025,
            "pro_rata_share": "0.10",
            "estimated_paid": "8000",
            "lines": [
                {"category": "cam", "actual_amount": "100000"},
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "draft"
    assert Decimal(body["tenant_share_amount"]) == Decimal("10000.00")
    assert Decimal(body["balance_due"]) == Decimal("2000.00")
    assert len(body["lines"]) == 1


@pytest.mark.asyncio
async def test_duplicate_reconciliation_rejected(client, accountant_user, cam_lease):
    headers = auth_headers(accountant_user)
    payload = {
        "lease_id": str(cam_lease.id),
        "year": 2025,
        "pro_rata_share": "0.10",
        "lines": [{"category": "cam", "actual_amount": "100000"}],
    }
    first = await client.post("/api/v1/cam/reconciliations", headers=headers, json=payload)
    assert first.status_code == 201
    dup = await client.post("/api/v1/cam/reconciliations", headers=headers, json=payload)
    assert dup.status_code == 409


@pytest.mark.asyncio
async def test_create_seeds_lines_from_operating_expenses(
    client, accountant_user, cam_lease, db_session
):
    # Seed operating expenses for the lease-year.
    db_session.add_all(
        [
            OperatingExpense(
                lease_id=cam_lease.id, organization_id=None, year=2025,
                category="cam", actual=Decimal("80000"),
            ),
            OperatingExpense(
                lease_id=cam_lease.id, organization_id=None, year=2025,
                category="taxes", actual=Decimal("20000"),
            ),
        ]
    )
    await db_session.commit()

    headers = auth_headers(accountant_user)
    resp = await client.post(
        "/api/v1/cam/reconciliations",
        headers=headers,
        json={"lease_id": str(cam_lease.id), "year": 2025, "pro_rata_share": "0.10"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body["lines"]) == 2
    assert Decimal(body["total_pool"]) == Decimal("100000.00")
    assert Decimal(body["tenant_share_amount"]) == Decimal("10000.00")


@pytest.mark.asyncio
async def test_update_recomputes_draft(client, accountant_user, cam_lease):
    headers = auth_headers(accountant_user)
    created = await client.post(
        "/api/v1/cam/reconciliations",
        headers=headers,
        json={
            "lease_id": str(cam_lease.id),
            "year": 2025,
            "pro_rata_share": "0.10",
            "lines": [{"category": "cam", "actual_amount": "100000"}],
        },
    )
    recon_id = created.json()["id"]
    resp = await client.patch(
        f"/api/v1/cam/reconciliations/{recon_id}",
        headers=headers,
        json={"estimated_paid": "12000"},
    )
    assert resp.status_code == 200
    assert Decimal(resp.json()["balance_due"]) == Decimal("-2000.00")


@pytest.mark.asyncio
async def test_finalize_blocks_further_edits(client, accountant_user, cam_lease):
    headers = auth_headers(accountant_user)
    created = await client.post(
        "/api/v1/cam/reconciliations",
        headers=headers,
        json={
            "lease_id": str(cam_lease.id),
            "year": 2025,
            "pro_rata_share": "0.10",
            "lines": [{"category": "cam", "actual_amount": "100000"}],
        },
    )
    recon_id = created.json()["id"]
    fin = await client.post(
        f"/api/v1/cam/reconciliations/{recon_id}/finalize", headers=headers
    )
    assert fin.status_code == 200
    assert fin.json()["status"] == "finalized"

    # Edits and deletes are now rejected.
    patched = await client.patch(
        f"/api/v1/cam/reconciliations/{recon_id}",
        headers=headers,
        json={"estimated_paid": "1"},
    )
    assert patched.status_code == 409
    deleted = await client.delete(
        f"/api/v1/cam/reconciliations/{recon_id}", headers=headers
    )
    assert deleted.status_code == 409


@pytest.mark.asyncio
async def test_post_to_gl_requires_finalized(client, accountant_user, cam_lease):
    headers = auth_headers(accountant_user)
    created = await client.post(
        "/api/v1/cam/reconciliations",
        headers=headers,
        json={
            "lease_id": str(cam_lease.id),
            "year": 2025,
            "pro_rata_share": "0.10",
            "estimated_paid": "8000",
            "lines": [{"category": "cam", "actual_amount": "100000"}],
        },
    )
    recon_id = created.json()["id"]
    resp = await client.post(
        f"/api/v1/cam/reconciliations/{recon_id}/post-to-gl", headers=headers
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_to_gl_creates_journal_entry(client, accountant_user, cam_lease):
    headers = auth_headers(accountant_user)
    created = await client.post(
        "/api/v1/cam/reconciliations",
        headers=headers,
        json={
            "lease_id": str(cam_lease.id),
            "year": 2025,
            "pro_rata_share": "0.10",
            "estimated_paid": "8000",
            "lines": [{"category": "cam", "actual_amount": "100000"}],
        },
    )
    recon_id = created.json()["id"]
    await client.post(f"/api/v1/cam/reconciliations/{recon_id}/finalize", headers=headers)

    resp = await client.post(
        f"/api/v1/cam/reconciliations/{recon_id}/post-to-gl", headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["posted"] is True
    assert body["journal_entry_id"] is not None
    assert Decimal(body["balance_due"]) == Decimal("2000.00")

    # The CAM journal entry is visible in the GL, balanced at the true-up amount.
    entries = await client.get(
        "/api/v1/gl/journal-entries?source=cam", headers=headers
    )
    assert entries.status_code == 200
    je = entries.json()
    assert len(je) == 1
    total_debit = sum(Decimal(line["debit"]) for line in je[0]["lines"])
    assert total_debit == Decimal("2000.00")


@pytest.mark.asyncio
async def test_post_to_gl_idempotent_repost(client, accountant_user, cam_lease):
    headers = auth_headers(accountant_user)
    created = await client.post(
        "/api/v1/cam/reconciliations",
        headers=headers,
        json={
            "lease_id": str(cam_lease.id),
            "year": 2025,
            "pro_rata_share": "0.10",
            "estimated_paid": "8000",
            "lines": [{"category": "cam", "actual_amount": "100000"}],
        },
    )
    recon_id = created.json()["id"]
    await client.post(f"/api/v1/cam/reconciliations/{recon_id}/finalize", headers=headers)
    await client.post(f"/api/v1/cam/reconciliations/{recon_id}/post-to-gl", headers=headers)
    await client.post(f"/api/v1/cam/reconciliations/{recon_id}/post-to-gl", headers=headers)

    entries = await client.get(
        "/api/v1/gl/journal-entries?source=cam", headers=headers
    )
    # Re-posting replaces rather than duplicates the entry.
    assert len(entries.json()) == 1


# ─── AI-assisted reconciliation review (Feature 5) ───────────────────────────

@pytest.mark.asyncio
async def test_ai_review_viewer_forbidden(client, viewer_user, cam_lease):
    resp = await client.post(
        f"/api/v1/cam/reconciliations/{uuid.uuid4()}/ai-review",
        headers=auth_headers(viewer_user),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_ai_review_missing_reconciliation(client, accountant_user):
    resp = await client.post(
        f"/api/v1/cam/reconciliations/{uuid.uuid4()}/ai-review",
        headers=auth_headers(accountant_user),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_ai_review_cross_references_prior_year_and_clauses(
    client, db_session, accountant_user, cam_lease, monkeypatch
):
    """The reviewer must receive prior-year lines and the lease's recovery
    clauses so it can flag YoY variance and non-permitted charges."""
    from app.models.lease_abstract import LeaseAbstractClause
    from app.services import ai_service

    headers = auth_headers(accountant_user)

    # Prior-year reconciliation (2024) for year-over-year context.
    await client.post(
        "/api/v1/cam/reconciliations",
        headers=headers,
        json={
            "lease_id": str(cam_lease.id),
            "year": 2024,
            "pro_rata_share": "0.10",
            "lines": [{"category": "cam", "actual_amount": "100000"}],
        },
    )
    # Current-year reconciliation (2025) with a category that doubled and a new
    # category not in the prior year.
    created = await client.post(
        "/api/v1/cam/reconciliations",
        headers=headers,
        json={
            "lease_id": str(cam_lease.id),
            "year": 2025,
            "pro_rata_share": "0.10",
            "lines": [
                {"category": "cam", "actual_amount": "200000"},
                {"category": "marketing", "actual_amount": "50000"},
            ],
        },
    )
    assert created.status_code == 201, created.text
    recon_id = created.json()["id"]

    # Abstracted recovery clause restricting permitted categories.
    clause = LeaseAbstractClause(
        lease_id=cam_lease.id,
        organization_id=None,
        category_key="expense_recoverables",
        status="contains_content",
        content={"recoverable_expenses": "CAM and taxes only; no marketing."},
    )
    db_session.add(clause)
    await db_session.commit()

    captured: dict = {}

    async def fake_review(*, year, lines, prior_year, prior_lines, lease_clauses):
        captured["year"] = year
        captured["lines"] = lines
        captured["prior_year"] = prior_year
        captured["prior_lines"] = prior_lines
        captured["lease_clauses"] = lease_clauses
        return {
            "summary": "1 anomaly found.",
            "anomalies": [
                {
                    "category": "marketing",
                    "anomaly_type": "not_permitted",
                    "severity": "high",
                    "message": "Marketing is not a lease-permitted recovery.",
                    "recommendation": "Remove the marketing charge.",
                }
            ],
        }

    monkeypatch.setattr(ai_service, "review_cam_reconciliation", fake_review)

    resp = await client.post(
        f"/api/v1/cam/reconciliations/{recon_id}/ai-review", headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["year"] == 2025
    assert body["prior_year"] == 2024
    assert len(body["anomalies"]) == 1
    assert body["anomalies"][0]["anomaly_type"] == "not_permitted"

    # The service received both subsystems' data.
    assert captured["prior_year"] == 2024
    assert {l["category"] for l in captured["prior_lines"]} == {"cam"}
    assert {l["category"] for l in captured["lines"]} == {"cam", "marketing"}
    assert "Expense/Recoverables" in captured["lease_clauses"]


@pytest.mark.asyncio
async def test_ai_review_degrades_when_unconfigured(
    client, accountant_user, cam_lease, monkeypatch
):
    from app.services import ai_service

    headers = auth_headers(accountant_user)
    created = await client.post(
        "/api/v1/cam/reconciliations",
        headers=headers,
        json={
            "lease_id": str(cam_lease.id),
            "year": 2025,
            "pro_rata_share": "0.10",
            "lines": [{"category": "cam", "actual_amount": "100000"}],
        },
    )
    recon_id = created.json()["id"]

    async def fake_review(**kwargs):
        raise ai_service.AIUnavailableError("AI assist is not configured")

    monkeypatch.setattr(ai_service, "review_cam_reconciliation", fake_review)

    resp = await client.post(
        f"/api/v1/cam/reconciliations/{recon_id}/ai-review", headers=headers
    )
    assert resp.status_code == 503, resp.text
