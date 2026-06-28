# Observability & Background Jobs

This document describes how SwiftLease emits logs, reports errors, exposes
health/readiness, and runs its background scheduler — and how those behave when
the backend is scaled to more than one replica.

## Logging

All runtime logging flows through a single root-logger configuration in
`backend/app/utils/logging_config.py`, invoked once at startup
(`app.main` and the `start.py` entrypoint import path). Application code uses
standard module loggers (`logging.getLogger(__name__)`) — `print()` is no
longer used for runtime output.

Two environment variables control output:

| Variable     | Values                         | Default | Purpose |
|--------------|--------------------------------|---------|---------|
| `LOG_LEVEL`  | `DEBUG`/`INFO`/`WARNING`/`ERROR` | `INFO`  | Root log level |
| `LOG_FORMAT` | `plain` / `json`               | `plain` | `json` emits one structured object per line for log aggregation (CloudWatch, Loki, Datadog). `plain` is human-readable for local dev. |

In `docker-compose.yml` the backend defaults to `LOG_FORMAT=json` and
`APP_ENV=production`. Structured logs include `timestamp`, `level`, `logger`,
`message`, `env`, and any structured context passed via `extra=` (for example
scheduled jobs log `job_id` and `duration_ms`).

## Error tracking (Sentry)

Sentry is **optional** and disabled unless `SENTRY_DSN` is set. When set (and
the `sentry-sdk` package is installed, which it is via `requirements.txt`),
errors are reported automatically.

| Variable                     | Default | Purpose |
|------------------------------|---------|---------|
| `SENTRY_DSN`                 | *(empty)* | Enables Sentry when non-empty |
| `APP_ENV`                    | `development` | Tags events with the environment |
| `SENTRY_TRACES_SAMPLE_RATE`  | `0.0`   | Performance-trace sample rate (0–1) |

If `SENTRY_DSN` is set but the package is missing, the app logs a warning and
continues without error tracking.

## Health vs. readiness probes

| Endpoint            | Semantics | Checks |
|---------------------|-----------|--------|
| `GET /api/v1/health` | **Liveness** — the process is up | static version/uptime info |
| `GET /api/v1/readyz` | **Readiness** — can serve traffic | database connectivity + scheduler running |

`/readyz` returns HTTP `503` with a per-check breakdown when a dependency is
unavailable, so orchestrators hold traffic until the app is healthy. The
`docker-compose.yml` backend healthcheck polls `/readyz`.

## Background scheduler & scaling model

Background jobs (reminders, SLA escalation, recurring tickets, webhook retries,
scheduled reports, billing hygiene, audit-log pruning, etc.) run in-process via
APScheduler — see `backend/app/tasks/scheduler.py`.

### Run-once across replicas

Each backend replica runs its own APScheduler, so without coordination a job
would fire on every replica (double-sending emails, double-posting tickets).
To prevent this, every job is wrapped by `run_tracked` in
`backend/app/tasks/job_status.py`, which acquires a **Postgres advisory lock**
(`pg_try_advisory_lock`) keyed by the job id before running. If another replica
already holds the lock, the job is recorded as `skipped` and exits. This makes
horizontal scaling of the backend safe with no extra infrastructure.

### Failure capture & visibility

`run_tracked` also records each run's outcome (status, error, duration, run and
failure counts) in an in-memory registry and logs start/finish/failure with
structured context. A failing job is logged with a full traceback and can never
crash the scheduler or hide other jobs.

Operators can inspect job health in the **admin SPA dashboard** ("Background
jobs" panel), backed by `GET /admin/v1/metrics/jobs`, which reports each job's
next scheduled run plus its last execution status, error, and duration.

> Note: the status registry is per-process. In a multi-replica deployment each
> replica reports the jobs it has executed; the advisory lock guarantees the
> underlying work still happens exactly once.
