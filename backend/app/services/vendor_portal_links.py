"""Helpers for building (and authorising) deep links into the vendor portal.

Centralises the portal-token lifecycle and URL construction so scheduled tasks
(e.g. the COI expiration reminder) can deep-link a vendor straight to their
self-service re-upload page without duplicating the token logic that lives in
``app.routers.vendor_portal``.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.models.vendor import Vendor

# Keep in sync with app.routers.vendor_portal._TOKEN_TTL_DAYS.
PORTAL_TOKEN_TTL_DAYS = 30


def ensure_portal_token(vendor: Vendor) -> str:
    """Return a usable portal token for ``vendor``, minting one if needed.

    Generates a fresh token (and expiry) when the vendor has none or the
    existing token has expired. Mutates the passed instance; the caller is
    responsible for committing the surrounding transaction.
    """
    now = datetime.now(timezone.utc)
    expires = vendor.portal_token_expires_at
    if not vendor.portal_token or (expires is not None and expires < now):
        vendor.portal_token = secrets.token_hex(32)
        vendor.portal_token_expires_at = now + timedelta(days=PORTAL_TOKEN_TTL_DAYS)
    return vendor.portal_token


def vendor_portal_url(token: str, *, tab: str | None = None) -> str:
    """Build the public vendor-portal URL for ``token`` (optionally a tab)."""
    base = f"{settings.FRONTEND_URL.rstrip('/')}/vendor-portal?token={token}"
    if tab:
        base += f"&tab={tab}"
    return base


def vendor_reupload_url(token: str) -> str:
    """Deep link to the vendor portal's insurance / COI re-upload panel."""
    return vendor_portal_url(token, tab="insurance")
