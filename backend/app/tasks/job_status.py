"""Scheduled-job execution tracking and run-once coordination.

This module provides two pieces of background-job reliability infrastructure:

1. An in-memory **status registry** that records the outcome of every
   scheduled job run (last start, last success, last failure, duration, and
   the most recent error). This is surfaced to super-admins via
   ``GET /admin/v1/metrics/jobs`` so operators can see at a glance whether the
   nightly reminders, billing hygiene, webhook retries, etc. are running and
   succeeding — instead of failures vanishing into ``print()`` output.

2. A **Postgres advisory-lock guard** so that when more than one backend
   replica is running (each with its own APScheduler), a given job invocation
   executes on exactly one replica. Without this, horizontally scaling the
   backend would double-send reminder emails and double-post recurring tickets.

The registry is intentionally in-memory: it reflects the activity of the
current process and is cheap. In a multi-replica deployment each replica keeps
its own view; the advisory lock ensures the *work* happens once even though the
*scheduling* happens on every replica.
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable

from sqlalchemy import text

from app.database import engine

logger = logging.getLogger("app.tasks")

JobFn = Callable[[], Awaitable[None]]


@dataclass
class JobStatus:
    """Mutable record of a single scheduled job's most recent activity."""

    job_id: str
    last_started_at: str | None = None
    last_finished_at: str | None = None
    last_status: str | None = None  # "success" | "failed" | "skipped" | "running"
    last_error: str | None = None
    last_duration_ms: int | None = None
    run_count: int = 0
    failure_count: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class _Registry:
    jobs: dict[str, JobStatus] = field(default_factory=dict)

    def _get(self, job_id: str) -> JobStatus:
        status = self.jobs.get(job_id)
        if status is None:
            status = JobStatus(job_id=job_id)
            self.jobs[job_id] = status
        return status

    def mark_running(self, job_id: str) -> None:
        status = self._get(job_id)
        status.last_started_at = _now_iso()
        status.last_status = "running"

    def mark_success(self, job_id: str, duration_ms: int) -> None:
        status = self._get(job_id)
        status.last_finished_at = _now_iso()
        status.last_status = "success"
        status.last_error = None
        status.last_duration_ms = duration_ms
        status.run_count += 1

    def mark_failure(self, job_id: str, error: str, duration_ms: int) -> None:
        status = self._get(job_id)
        status.last_finished_at = _now_iso()
        status.last_status = "failed"
        status.last_error = error
        status.last_duration_ms = duration_ms
        status.run_count += 1
        status.failure_count += 1

    def mark_skipped(self, job_id: str) -> None:
        status = self._get(job_id)
        status.last_status = "skipped"

    def snapshot(self) -> list[dict]:
        return [self.jobs[k].as_dict() for k in sorted(self.jobs)]


registry = _Registry()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _advisory_key(job_id: str) -> int:
    """Map a job id to a stable signed 64-bit key for ``pg_advisory_lock``."""
    digest = hashlib.sha256(job_id.encode("utf-8")).digest()[:8]
    return int.from_bytes(digest, "big", signed=True)


def run_tracked(job_id: str, job_fn: JobFn) -> JobFn:
    """Wrap a scheduled coroutine with logging, status tracking, and a
    cross-replica advisory lock so it runs at most once per invocation.

    The returned coroutine never raises: any exception from ``job_fn`` is
    logged and recorded in the registry so a single failing job cannot tear
    down the scheduler or hide other jobs' output.
    """

    async def _wrapped() -> None:
        key = _advisory_key(job_id)
        # A dedicated AUTOCOMMIT connection holds the session-level advisory
        # lock for the duration of the job. The job itself opens its own
        # ``async_session`` (a separate connection), so this only gates execution.
        async with engine.connect() as conn:
            lock_conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
            got_lock = await lock_conn.scalar(
                text("SELECT pg_try_advisory_lock(:k)"), {"k": key}
            )
            if not got_lock:
                registry.mark_skipped(job_id)
                logger.info(
                    "Scheduled job skipped (lock held by another replica)",
                    extra={"job_id": job_id},
                )
                return

            registry.mark_running(job_id)
            logger.info("Scheduled job started", extra={"job_id": job_id})
            started = time.monotonic()
            try:
                await job_fn()
            except Exception as exc:  # noqa: BLE001 - jobs must not crash scheduler
                duration_ms = int((time.monotonic() - started) * 1000)
                registry.mark_failure(job_id, repr(exc), duration_ms)
                logger.exception(
                    "Scheduled job failed",
                    extra={"job_id": job_id, "duration_ms": duration_ms},
                )
            else:
                duration_ms = int((time.monotonic() - started) * 1000)
                registry.mark_success(job_id, duration_ms)
                logger.info(
                    "Scheduled job finished",
                    extra={"job_id": job_id, "duration_ms": duration_ms},
                )
            finally:
                await lock_conn.execute(
                    text("SELECT pg_advisory_unlock(:k)"), {"k": key}
                )

    _wrapped.__name__ = f"tracked_{job_id}"
    return _wrapped
