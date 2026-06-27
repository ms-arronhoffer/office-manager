from datetime import date, timedelta

import pytest

from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_summary_active_leases_excludes_deleted(client, admin_user, sample_office):
    """Deleted (soft-deleted) leases must not be counted as active leases."""
    future = (date.today() + timedelta(days=365)).isoformat()

    created_ids = []
    for i in range(2):
        resp = await client.post(
            "/api/v1/leases",
            headers=auth_headers(admin_user),
            json={
                "lease_name": f"Active Lease {i}",
                "office_id": str(sample_office.id),
                "expiration_year": 2099,
                "lease_expiration": future,
            },
        )
        assert resp.status_code == 201
        created_ids.append(resp.json()["id"])

    # Both leases counted before any deletion.
    summary = await client.get("/api/v1/dashboard/summary", headers=auth_headers(admin_user))
    assert summary.status_code == 200
    assert summary.json()["active_leases"] == 2

    # Soft-delete one lease.
    delete_resp = await client.delete(
        f"/api/v1/leases/{created_ids[0]}",
        headers=auth_headers(admin_user),
    )
    assert delete_resp.status_code == 204

    # The deleted lease must no longer be counted.
    summary = await client.get("/api/v1/dashboard/summary", headers=auth_headers(admin_user))
    assert summary.status_code == 200
    assert summary.json()["active_leases"] == 1
