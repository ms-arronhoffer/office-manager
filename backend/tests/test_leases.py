import pytest
from decimal import Decimal
from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_create_lease(client, admin_user, sample_office):
    resp = await client.post("/api/v1/leases", headers=auth_headers(admin_user), json={
        "lease_name": "Test Lease",
        "office_id": str(sample_office.id),
        "expiration_year": 2027,
        "lessor_name": "ACME Properties",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["lease_name"] == "Test Lease"
    assert data["expiration_year"] == 2027


@pytest.mark.asyncio
async def test_list_leases(client, admin_user, sample_office):
    # Create two leases
    for i in range(2):
        await client.post("/api/v1/leases", headers=auth_headers(admin_user), json={
            "lease_name": f"Lease {i}",
            "office_id": str(sample_office.id),
            "expiration_year": 2027,
        })

    resp = await client.get("/api/v1/leases", headers=auth_headers(admin_user))
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


@pytest.mark.asyncio
async def test_delete_lease(client, admin_user, sample_office):
    create_resp = await client.post("/api/v1/leases", headers=auth_headers(admin_user), json={
        "lease_name": "To Delete",
        "office_id": str(sample_office.id),
        "expiration_year": 2026,
    })
    lease_id = create_resp.json()["id"]

    resp = await client.delete(
        f"/api/v1/leases/{lease_id}",
        headers=auth_headers(admin_user),
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_create_lease_succeeds_when_activity_log_fails(
    client, admin_user, sample_office, monkeypatch
):
    """A failure in best-effort activity logging must not 500 the create.

    Regression: the lease is committed before log_activity runs, so a raised
    error there previously surfaced as "Failed to create lease" even though the
    lease persisted.
    """
    import app.routers.leases as leases_router

    async def boom(*args, **kwargs):
        raise RuntimeError("activity log unavailable")

    monkeypatch.setattr(leases_router, "log_activity", boom)

    resp = await client.post(
        "/api/v1/leases",
        headers=auth_headers(admin_user),
        json={
            "lease_name": "Resilient Lease",
            "office_id": str(sample_office.id),
            "expiration_year": 2030,
            "lessor_name": "ACME Properties",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["lease_name"] == "Resilient Lease"

    # And it is actually retrievable.
    listed = await client.get("/api/v1/leases", headers=auth_headers(admin_user))
    assert any(l["lease_name"] == "Resilient Lease" for l in listed.json()["items"])


@pytest.mark.asyncio
async def test_create_lease_succeeds_when_search_vector_update_fails(
    client, admin_user, sample_office, monkeypatch
):
    """A failure updating the full-text search vector must not 500 the create.

    Like activity logging, search-vector maintenance is a best-effort side
    effect that runs after the lease is committed; a raised error there must not
    surface as "Failed to create lease" when the lease actually persisted.
    """
    import app.routers.leases as leases_router

    async def boom(*args, **kwargs):
        raise RuntimeError("search vector update unavailable")

    monkeypatch.setattr(leases_router, "update_search_vector", boom)

    resp = await client.post(
        "/api/v1/leases",
        headers=auth_headers(admin_user),
        json={
            "lease_name": "Indexed Lease",
            "office_id": str(sample_office.id),
            "expiration_year": 2031,
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["lease_name"] == "Indexed Lease"

    listed = await client.get("/api/v1/leases", headers=auth_headers(admin_user))
    assert any(l["lease_name"] == "Indexed Lease" for l in listed.json()["items"])

@pytest.mark.asyncio
async def test_create_lease_normalizes_long_currency(client, admin_user, sample_office):
    """An AI-extracted currency like "US Dollars" must not overflow varchar(3).

    Previously such a value raised a database StringDataRightTruncation error,
    surfacing as a 500 on POST /leases and silently blocking the document
    attachment and abstract pre-fill that run only after a successful create.
    """
    resp = await client.post(
        "/api/v1/leases",
        headers=auth_headers(admin_user),
        json={
            "lease_name": "Currency Lease",
            "office_id": str(sample_office.id),
            "expiration_year": 2032,
            "currency": "US Dollars",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["currency"] == "USD"


@pytest.mark.asyncio
async def test_update_lease_normalizes_long_currency(client, admin_user, sample_office):
    create = await client.post(
        "/api/v1/leases",
        headers=auth_headers(admin_user),
        json={
            "lease_name": "Currency Update Lease",
            "office_id": str(sample_office.id),
            "expiration_year": 2033,
        },
    )
    assert create.status_code == 201, create.text
    lease_id = create.json()["id"]

    resp = await client.put(
        f"/api/v1/leases/{lease_id}",
        headers=auth_headers(admin_user),
        json={"currency": "Euro"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["currency"] == "EUR"


@pytest.mark.asyncio
async def test_update_lease_preserves_currency_when_not_provided(
    client, admin_user, sample_office
):
    """Updating other fields must not reset the stored currency.

    The currency schema field defaults to "USD", so the update path must rely on
    exclude_unset to leave an existing currency untouched when it isn't sent.
    """
    create = await client.post(
        "/api/v1/leases",
        headers=auth_headers(admin_user),
        json={
            "lease_name": "Keep Currency Lease",
            "office_id": str(sample_office.id),
            "expiration_year": 2034,
            "currency": "EUR",
        },
    )
    assert create.status_code == 201, create.text
    lease_id = create.json()["id"]

    resp = await client.put(
        f"/api/v1/leases/{lease_id}",
        headers=auth_headers(admin_user),
        json={"lease_name": "Keep Currency Lease (renamed)"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["currency"] == "EUR"

@pytest.mark.asyncio
async def test_create_lease_caps_long_text_fields(client, admin_user, sample_office):
    """Overlong AI-extracted text must not overflow the varchar(255) columns.

    A full notice clause pasted into ``notice_period`` (or an overlong
    ``lease_name``) previously raised a database StringDataRightTruncation error,
    surfacing as a 500 on POST /leases and silently blocking the document
    attachment and abstract pre-fill that run only after a successful create.
    """
    resp = await client.post(
        "/api/v1/leases",
        headers=auth_headers(admin_user),
        json={
            "lease_name": "L" * 400,
            "office_id": str(sample_office.id),
            "expiration_year": 2035,
            "notice_period": "N" * 400,
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert len(data["lease_name"]) == 255
    assert len(data["notice_period"]) == 255


@pytest.mark.asyncio
async def test_create_lease_coerces_freetext_enum_fields(client, admin_user, sample_office):
    """Free-text / AI-extracted enum-style values must not overflow their columns.

    ``accounting_standard`` (varchar 10), ``lease_classification`` (varchar 20)
    and ``payment_frequency`` (varchar 20) are coerced to a valid code or None,
    so values like "ASC 842 / IFRS 16" can never 500 the create.
    """
    resp = await client.post(
        "/api/v1/leases",
        headers=auth_headers(admin_user),
        json={
            "lease_name": "Enum Lease",
            "office_id": str(sample_office.id),
            "expiration_year": 2036,
            "accounting_standard": "ASC 842 / IFRS 16 standard",
            "lease_classification": "operating lease - modified gross",
            "payment_frequency": "monthly with quarterly true-up",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["accounting_standard"] is None
    assert data["lease_classification"] is None
    assert data["payment_frequency"] is None


@pytest.mark.asyncio
async def test_create_lease_preserves_valid_enum_fields(client, admin_user, sample_office):
    resp = await client.post(
        "/api/v1/leases",
        headers=auth_headers(admin_user),
        json={
            "lease_name": "Valid Enum Lease",
            "office_id": str(sample_office.id),
            "expiration_year": 2037,
            "accounting_standard": "asc842",
            "lease_classification": "operating",
            "payment_frequency": "monthly",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["accounting_standard"] == "asc842"
    assert data["lease_classification"] == "operating"
    assert data["payment_frequency"] == "monthly"


@pytest.mark.asyncio
async def test_update_lease_caps_long_notice_period(client, admin_user, sample_office):
    create = await client.post(
        "/api/v1/leases",
        headers=auth_headers(admin_user),
        json={
            "lease_name": "Update Cap Lease",
            "office_id": str(sample_office.id),
            "expiration_year": 2038,
        },
    )
    assert create.status_code == 201, create.text
    lease_id = create.json()["id"]

    resp = await client.put(
        f"/api/v1/leases/{lease_id}",
        headers=auth_headers(admin_user),
        json={"notice_period": "N" * 400},
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["notice_period"]) == 255


@pytest.mark.asyncio
async def test_create_lease_drops_out_of_range_numeric_fields(
    client, admin_user, sample_office
):
    """Out-of-range AI-extracted numbers must not overflow the NUMERIC columns.

    Rates are ``Numeric(8, 6)`` (max 2 integer digits) and monetary amounts are
    ``Numeric(15, 2)``. A rate >= 100 or an absurdly large amount previously
    raised a database NumericValueOutOfRange error, surfacing as a 500 on POST
    /leases and silently blocking the document attachment and abstract pre-fill
    that run only after a successful create. Such values are coerced to None.
    """
    resp = await client.post(
        "/api/v1/leases",
        headers=auth_headers(admin_user),
        json={
            "lease_name": "Overflow Lease",
            "office_id": str(sample_office.id),
            "expiration_year": 2039,
            "annual_escalation_rate": 100,
            "incremental_borrowing_rate": 250,
            "payment_amount": 99999999999999999,
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["annual_escalation_rate"] is None
    assert data["incremental_borrowing_rate"] is None
    assert data["payment_amount"] is None


@pytest.mark.asyncio
async def test_create_lease_parses_freetext_numeric_fields(
    client, admin_user, sample_office
):
    """Free-text numbers ("$1,250.50") must parse, and junk must coerce to None."""
    resp = await client.post(
        "/api/v1/leases",
        headers=auth_headers(admin_user),
        json={
            "lease_name": "Freetext Numeric Lease",
            "office_id": str(sample_office.id),
            "expiration_year": 2040,
            "payment_amount": "$1,250.50",
            "initial_direct_costs": "N/A",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert Decimal(data["payment_amount"]) == Decimal("1250.50")
    assert data["initial_direct_costs"] is None


@pytest.mark.asyncio
async def test_create_lease_preserves_valid_numeric_fields(
    client, admin_user, sample_office
):
    resp = await client.post(
        "/api/v1/leases",
        headers=auth_headers(admin_user),
        json={
            "lease_name": "Valid Numeric Lease",
            "office_id": str(sample_office.id),
            "expiration_year": 2041,
            "annual_escalation_rate": 0.03,
            "incremental_borrowing_rate": 0.045,
            "payment_amount": 12500.50,
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert Decimal(data["annual_escalation_rate"]) == Decimal("0.030000")
    assert Decimal(data["incremental_borrowing_rate"]) == Decimal("0.045000")
    assert Decimal(data["payment_amount"]) == Decimal("12500.50")


@pytest.mark.asyncio
async def test_update_lease_drops_out_of_range_rate(client, admin_user, sample_office):
    create = await client.post(
        "/api/v1/leases",
        headers=auth_headers(admin_user),
        json={
            "lease_name": "Update Numeric Lease",
            "office_id": str(sample_office.id),
            "expiration_year": 2042,
        },
    )
    assert create.status_code == 201, create.text
    lease_id = create.json()["id"]

    resp = await client.put(
        f"/api/v1/leases/{lease_id}",
        headers=auth_headers(admin_user),
        json={"annual_escalation_rate": 100},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["annual_escalation_rate"] is None
