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
from app.services.organization_integration_settings import PlaidSettings, legacy_settings

logger = logging.getLogger(__name__)


class PlaidApiError(Exception):
    """Raised when a Plaid API call fails."""

    def __init__(self, message: str, status_code: int | None = None, error_code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


def is_configured(config: PlaidSettings | None = None) -> bool:
    """True when Plaid credentials are present."""
    config = config or legacy_settings("plaid")
    return bool(config.is_enabled and config.client_id and config.secret)


def country_codes(config: PlaidSettings | None = None) -> list[str]:
    config = config or legacy_settings("plaid")
    return list(config.country_codes)


class PlaidClient:
    """Async client for the subset of Plaid endpoints the bank feed needs."""

    def __init__(self, *, config: PlaidSettings | None = None, base_url: str | None = None, timeout: float | None = None):
        self.config = config or legacy_settings("plaid")
        self.base_url = (base_url or self.config.api_base_url).rstrip("/")
        self.timeout = timeout if timeout is not None else self.config.timeout_seconds

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        body = {
            "client_id": self.config.client_id,
            "secret": self.config.secret,
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
            "country_codes": country_codes(self.config),
            "language": "en",
        }
        if self.config.redirect_uri:
            payload["redirect_uri"] = self.config.redirect_uri
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
            {"institution_id": institution_id, "country_codes": country_codes(self.config)},
        )

    async def get_institutions(self, *, count: int = 1) -> dict[str, Any]:
        return await self._post(
            "institutions/get", {"count": count, "offset": 0, "country_codes": country_codes(self.config)}
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
