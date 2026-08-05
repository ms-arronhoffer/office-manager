"""Minimal async Plaid client for the live bank feed.

Plaid authenticates every request with the ``client_id``/``secret`` pair in the
JSON body rather than a header, and exposes cursor-based incremental sync at
``/transactions/sync``.

Like :mod:`app.utils.payment_processor`, this degrades gracefully: when
``PLAID_CLIENT_ID``/``PLAID_SECRET`` are unset :func:`is_configured` returns
False and callers report an "unconfigured" state instead of raising, so dev and
test environments run without credentials.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class PlaidApiError(Exception):
    """Raised when a Plaid API call fails."""

    def __init__(self, message: str, status_code: int | None = None, error_code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


def is_configured() -> bool:
    """True when Plaid credentials are present."""
    return bool(settings.PLAID_CLIENT_ID and settings.PLAID_SECRET)


def country_codes() -> list[str]:
    return [c.strip().upper() for c in (settings.PLAID_COUNTRY_CODES or "US").split(",") if c.strip()]


class PlaidClient:
    """Async client for the subset of Plaid endpoints the bank feed needs."""

    def __init__(self, *, base_url: str | None = None, timeout: float | None = None):
        self.base_url = (base_url or settings.PLAID_API_BASE_URL).rstrip("/")
        self.timeout = timeout if timeout is not None else settings.PLAID_TIMEOUT_SECONDS

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        body = {
            "client_id": settings.PLAID_CLIENT_ID,
            "secret": settings.PLAID_SECRET,
            **payload,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as http:
                resp = await http.post(url, json=body)
        except httpx.HTTPError as exc:
            raise PlaidApiError(f"Network error calling Plaid: {exc}") from exc

        try:
            data = resp.json() or {}
        except ValueError:
            data = {}
        if resp.status_code >= 400:
            raise PlaidApiError(
                data.get("error_message") or f"Plaid API error {resp.status_code} for {path}",
                status_code=resp.status_code,
                error_code=data.get("error_code"),
            )
        return data

    async def create_link_token(self, *, client_user_id: str, client_name: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "user": {"client_user_id": client_user_id},
            "client_name": client_name,
            "products": ["transactions"],
            "country_codes": country_codes(),
            "language": "en",
        }
        if settings.PLAID_REDIRECT_URI:
            payload["redirect_uri"] = settings.PLAID_REDIRECT_URI
        return await self._post("link/token/create", payload)

    async def exchange_public_token(self, public_token: str) -> dict[str, Any]:
        return await self._post(
            "item/public_token/exchange", {"public_token": public_token}
        )

    async def get_accounts(self, access_token: str) -> dict[str, Any]:
        return await self._post("accounts/get", {"access_token": access_token})

    async def get_institution(self, institution_id: str) -> dict[str, Any]:
        return await self._post(
            "institutions/get_by_id",
            {"institution_id": institution_id, "country_codes": country_codes()},
        )

    async def get_item(self, access_token: str) -> dict[str, Any]:
        return await self._post("item/get", {"access_token": access_token})

    async def sync_transactions(
        self, access_token: str, cursor: str | None = None, *, count: int = 500
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"access_token": access_token, "count": count}
        # Omitting the cursor asks Plaid for the full history (initial backfill).
        if cursor:
            payload["cursor"] = cursor
        return await self._post("transactions/sync", payload)

    async def remove_item(self, access_token: str) -> dict[str, Any]:
        return await self._post("item/remove", {"access_token": access_token})
