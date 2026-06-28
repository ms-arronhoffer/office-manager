"""Centralized logging and error-tracking configuration.

This module is the single place that configures the root logger and (optionally)
initializes Sentry. It is imported and invoked once at application startup
(``app.main``) and by the container entrypoint (``start.py``) so that every
log line — whether emitted from a request handler, a background scheduler job,
or the bootstrap script — flows through the same handler/format.

Two output formats are supported, selected via ``settings.LOG_FORMAT``:

* ``plain`` — human-readable single-line output, ideal for local development.
* ``json`` — structured one-object-per-line output, ideal for log aggregation
  systems (CloudWatch, Loki, Datadog, etc.) in production.

Sentry is fully optional: it is only initialized when ``settings.SENTRY_DSN``
is set *and* the ``sentry_sdk`` package is importable. When either is missing,
the application runs unchanged with no error reporting.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from app.config import settings

_CONFIGURED = False

# Standard ``LogRecord`` attributes that should not be duplicated into the
# structured "extra" payload.
_RESERVED_LOG_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    """Render log records as compact single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "env": settings.APP_ENV,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # Surface any structured context passed via ``logger.info(..., extra={...})``.
        for key, value in record.__dict__.items():
            if key not in _RESERVED_LOG_ATTRS and not key.startswith("_"):
                payload[key] = value

        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """Configure the root logger. Idempotent — safe to call more than once."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    if settings.LOG_FORMAT.lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S%z",
            )
        )

    root = logging.getLogger()
    root.setLevel(level)
    # Replace any pre-existing handlers (e.g. uvicorn's defaults) so output is
    # consistent and not duplicated.
    root.handlers = [handler]

    # Tame noisy third-party loggers.
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    _CONFIGURED = True


def init_sentry() -> bool:
    """Initialize Sentry if configured. Returns True when enabled.

    No-ops (returning False) when ``SENTRY_DSN`` is unset or the optional
    ``sentry_sdk`` dependency is not installed.
    """
    if not settings.SENTRY_DSN:
        return False

    try:  # pragma: no cover - exercised only when the optional dep is present
        import sentry_sdk
    except ImportError:
        logging.getLogger(__name__).warning(
            "SENTRY_DSN is set but sentry-sdk is not installed; "
            "error tracking is disabled."
        )
        return False

    sentry_sdk.init(  # pragma: no cover - requires network/credentials
        dsn=settings.SENTRY_DSN,
        environment=settings.APP_ENV,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        release=__import__("os").environ.get("BUILD_SHA", "dev"),
    )
    logging.getLogger(__name__).info("Sentry error tracking enabled")
    return True
