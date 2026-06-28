"""Tests for observability (readiness probe) and background-job reliability."""
import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.tasks.job_status import _advisory_key, registry, run_tracked


@pytest.mark.asyncio
async def test_health_is_liveness(client: AsyncClient):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_readyz_reports_db_and_scheduler(client: AsyncClient):
    resp = await client.get("/api/v1/readyz")
    body = resp.json()
    # DB is reachable in tests; scheduler is not started, so expect not_ready/503
    # with a per-check breakdown showing the database check passed.
    assert "checks" in body
    assert body["checks"]["database"] == "ok"
    assert resp.status_code in (200, 503)


@pytest.mark.asyncio
async def test_run_tracked_records_success_and_failure():
    ran: list[int] = []

    async def ok_job():
        ran.append(1)

    async def bad_job():
        raise ValueError("boom")

    await run_tracked("test_ok", ok_job)()
    await run_tracked("test_bad", bad_job)()

    snap = {r["job_id"]: r for r in registry.snapshot()}
    assert ran == [1]
    assert snap["test_ok"]["last_status"] == "success"
    assert snap["test_bad"]["last_status"] == "failed"
    assert snap["test_bad"]["failure_count"] == 1
    assert "boom" in snap["test_bad"]["last_error"]


@pytest.mark.asyncio
async def test_advisory_lock_runs_job_once_concurrently():
    counter: list[int] = []
    gate = asyncio.Event()

    async def slow_job():
        counter.append(1)
        await gate.wait()

    wrapped = run_tracked("test_lock", slow_job)
    first = asyncio.create_task(wrapped())
    await asyncio.sleep(0.2)  # let first acquire the advisory lock
    second = asyncio.create_task(wrapped())  # should be skipped
    await second
    gate.set()
    await first

    # Only one acquired the lock and executed the body.
    assert counter == [1]


def test_advisory_key_stable_and_signed():
    key = _advisory_key("test_lock")
    assert _advisory_key("test_lock") == key
    assert -(2**63) <= key < 2**63
