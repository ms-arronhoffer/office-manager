"""Authenticated HTTP client for the Buildium Open API.

Buildium authenticates with two headers (``x-buildium-client-id`` /
``x-buildium-client-secret``) rather than OAuth, and paginates list endpoints
with ``limit``/``offset`` query params (max 100/page). It enforces a modest
rate limit and returns ``429`` (with an optional ``Retry-After`` header) when
exceeded, so every request goes through bounded, jittered-backoff retry —
mirroring ``app.services.ai_service._post_with_retry``.
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, AsyncIterator

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class BuildiumApiError(Exception):
    """Raised when a Buildium API call fails after all retries."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class BuildiumClient:
    """Minimal async client for the subset of Buildium endpoints needed to
    migrate rental properties, units, owners, tenants, leases, vendors, bills,
    bank accounts, GL accounts/transactions, and tasks."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        base_url: str | None = None,
        *,
        timeout: float | None = None,
        max_retries: int | None = None,
        retry_base_seconds: float | None = None,
        page_size: int | None = None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = (base_url or settings.BUILDIUM_API_BASE_URL).rstrip("/")
        self.timeout = timeout if timeout is not None else settings.BUILDIUM_TIMEOUT_SECONDS
        self.max_retries = max_retries if max_retries is not None else settings.BUILDIUM_MAX_RETRIES
        self.retry_base_seconds = (
            retry_base_seconds if retry_base_seconds is not None else settings.BUILDIUM_RETRY_BASE_SECONDS
        )
        self.page_size = page_size if page_size is not None else settings.BUILDIUM_PAGE_SIZE

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "x-buildium-client-id": self.client_id,
            "x-buildium-client-secret": self.client_secret,
            "Accept": "application/json",
        }

    async def _request(
        self, method: str, path: str, *, params: dict[str, Any] | None = None
    ) -> httpx.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        attempts = max(0, self.max_retries) + 1
        last_exc: Exception | None = None
        resp: httpx.Response | None = None

        for attempt in range(attempts):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.request(
                        method, url, params=params, headers=self._headers
                    )
            except httpx.HTTPError as exc:  # network / timeout
                last_exc = exc
                resp = None
                if attempt == attempts - 1:
                    raise BuildiumApiError(f"Network error calling Buildium: {exc}") from exc
            else:
                if resp.status_code in _RETRYABLE_STATUS and attempt < attempts - 1:
                    logger.info(
                        "Buildium returned retryable %s for %s (attempt %d/%d)",
                        resp.status_code, path, attempt + 1, attempts,
                    )
                else:
                    if resp.status_code >= 400:
                        raise BuildiumApiError(
                            f"Buildium API error {resp.status_code} for {path}: {resp.text[:500]}",
                            status_code=resp.status_code,
                        )
                    return resp

            # Backoff before next attempt — honor Retry-After when present.
            retry_after = resp.headers.get("Retry-After") if resp is not None else None
            if retry_after:
                try:
                    delay = float(retry_after)
                except ValueError:
                    delay = self.retry_base_seconds * (2 ** attempt)
            else:
                delay = self.retry_base_seconds * (2 ** attempt)
            await asyncio.sleep(random.uniform(0.0, delay) if delay > 0 else 0.0)

        if last_exc:
            raise BuildiumApiError(f"Buildium request failed: {last_exc}") from last_exc
        raise BuildiumApiError(f"Buildium request to {path} failed after {attempts} attempts")

    async def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        resp = await self._request("GET", path, params=params)
        return resp.json()

    async def test_connection(self) -> tuple[bool, str | None]:
        """Cheap credential check used by the "Test connection" UI action."""
        try:
            await self.get("rentals", params={"limit": 1, "offset": 0})
        except BuildiumApiError as exc:
            return False, str(exc)
        return True, None

    async def paginate(
        self, path: str, *, extra_params: dict[str, Any] | None = None
    ) -> AsyncIterator[dict]:
        """Yield every record from a Buildium list endpoint, walking pages via
        ``limit``/``offset`` until a short page signals the end."""
        offset = 0
        while True:
            params = {"limit": self.page_size, "offset": offset, **(extra_params or {})}
            page = await self.get(path, params=params)
            items = page if isinstance(page, list) else page.get("results", page.get("Items", []))
            if not items:
                return
            for item in items:
                yield item
            if len(items) < self.page_size:
                return
            offset += self.page_size

    # ── Entity-specific list helpers ──────────────────────────────────────
    def list_properties(self) -> AsyncIterator[dict]:
        return self.paginate("rentals")

    def list_units(self, property_id: str) -> AsyncIterator[dict]:
        return self.paginate(f"rentals/{property_id}/units")

    def list_owners(self) -> AsyncIterator[dict]:
        return self.paginate("rentals/owners")

    def list_vendors(self) -> AsyncIterator[dict]:
        return self.paginate("vendors")

    def list_tenants(self) -> AsyncIterator[dict]:
        return self.paginate("leases/tenants")

    def list_leases(self) -> AsyncIterator[dict]:
        return self.paginate("leases")

    def list_bank_accounts(self) -> AsyncIterator[dict]:
        return self.paginate("bankaccounts")

    def list_gl_accounts(self) -> AsyncIterator[dict]:
        return self.paginate("glaccounts")

    def list_bills(self) -> AsyncIterator[dict]:
        return self.paginate("bills")

    def list_tasks(self) -> AsyncIterator[dict]:
        return self.paginate("tasks")
