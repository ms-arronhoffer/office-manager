"""Shared datetime utility helpers."""
from __future__ import annotations

from datetime import datetime, timezone


def as_utc(dt: datetime) -> datetime:
    """Return *dt* with UTC timezone attached; adds UTC if the datetime is naive."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
