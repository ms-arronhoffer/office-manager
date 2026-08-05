"""Authenticated HTTP client for the QuickBooks Online Accounting API.

QBO uses OAuth2 authorization-code with a rotating refresh token: the access
token lives ~1 hour, the refresh token ~100 days and is *replaced* on most
refreshes, so callers must persist whatever comes back (see
``app.services.quickbooks.sync_service``).

Retries mirror ``app.services.buildium.client``: bounded, jittered backoff on
429/5xx only. A 401 is surfaced as a distinct error so the sync layer can
refresh the token and retry once rather than treating it as fatal.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_BACKOFF_SECONDS = 60.0

# Scope needed to read the chart of accounts and write journal entries.
QBO_SCOPE = "com.intuit.quickbooks.accounting"


class QuickBooksApiError(Exception):
    """Raised when a QuickBooks API call fails."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class QuickBooksAuthError(QuickBooksApiError):
    """Raised on 401 so the caller can refresh the access token and retry."""


@dataclass
class TokenSet:
    """Tokens returned by the QBO token endpoint."""

    access_token: str
    refresh_token: str
    access_token_expires_at: datetime
    refresh_token_expires_at: datetime | None = None


def is_configured() -> bool:
    """True when the Intuit app credentials are present."""
    return bool(settings.QBO_CLIENT_ID and settings.QBO_CLIENT_SECRET)


def authorize_url(state: str) -> str:
    """Build the Intuit consent URL the admin is redirected to."""
    params = {
        "client_id": settings.QBO_CLIENT_ID,
        "response_type": "code",
        "scope": QBO_SCOPE,
        "redirect_uri": settings.QBO_REDIRECT_URI,
        "state": state,
    }
    return f"{settings.QBO_AUTH_URL}?{urlencode(params)}"


def _basic_auth_header() -> str:
    raw = f"{settings.QBO_CLIENT_ID}:{settings.QBO_CLIENT_SECRET}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _token_set_from_payload(payload: dict[str, Any], *, fallback_refresh: str = "") -> TokenSet:
    now = datetime.now(timezone.utc)
    access = payload.get("access_token")
    if not access:
        raise QuickBooksApiError("QuickBooks token response did not include an access_token.")
    refresh = payload.get("refresh_token") or fallback_refresh
    if not refresh:
        raise QuickBooksApiError("QuickBooks token response did not include a refresh_token.")
    expires_in = int(payload.get("expires_in") or 3600)
    refresh_expires_in = payload.get("x_refresh_token_expires_in")
    return TokenSet(
        access_token=access,
        refresh_token=refresh,
        access_token_expires_at=now + timedelta(seconds=expires_in),
        refresh_token_expires_at=(
            now + timedelta(seconds=int(refresh_expires_in)) if refresh_expires_in else None
        ),
    )


async def _post_token(data: dict[str, str]) -> dict[str, Any]:
    headers = {
        "Authorization": _basic_auth_header(),
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    try:
        async with httpx.AsyncClient(timeout=settings.QBO_TIMEOUT_SECONDS) as http:
            resp = await http.post(settings.QBO_TOKEN_URL, data=data, headers=headers)
    except httpx.HTTPError as exc:
        raise QuickBooksApiError(f"Network error calling QuickBooks token endpoint: {exc}") from exc
    if resp.status_code >= 400:
        raise QuickBooksApiError(
            f"QuickBooks token endpoint returned {resp.status_code}: {resp.text[:300]}",
            status_code=resp.status_code,
        )
    try:
        return resp.json()
    except ValueError as exc:
        raise QuickBooksApiError("QuickBooks token endpoint returned a non-JSON body.") from exc


async def exchange_code(code: str) -> TokenSet:
    """Trade an authorization code for the initial token pair."""
    payload = await _post_token(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.QBO_REDIRECT_URI,
        }
    )
    return _token_set_from_payload(payload)


async def refresh_tokens(refresh_token: str) -> TokenSet:
    """Exchange a refresh token for a new pair.

    Intuit rotates the refresh token on most refreshes, so the returned value
    must replace the stored one.
    """
    payload = await _post_token(
        {"grant_type": "refresh_token", "refresh_token": refresh_token}
    )
    return _token_set_from_payload(payload, fallback_refresh=refresh_token)


class QuickBooksClient:
    """Minimal async client for the QBO Accounting API subset we use."""

    def __init__(
        self,
        access_token: str,
        realm_id: str,
        *,
        base_url: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        retry_base_seconds: float | None = None,
    ):
        self.access_token = access_token
        self.realm_id = realm_id
        self.base_url = (base_url or settings.QBO_API_BASE_URL).rstrip("/")
        self.timeout = timeout if timeout is not None else settings.QBO_TIMEOUT_SECONDS
        self.max_retries = max_retries if max_retries is not None else settings.QBO_MAX_RETRIES
        self.retry_base_seconds = (
            retry_base_seconds
            if retry_base_seconds is not None
            else settings.QBO_RETRY_BASE_SECONDS
        )

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/{self.realm_id}/{path.lstrip('/')}"
        query = {"minorversion": settings.QBO_MINOR_VERSION, **(params or {})}
        attempts = max(0, self.max_retries) + 1
        last_exc: Exception | None = None
        resp: httpx.Response | None = None

        for attempt in range(attempts):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as http:
                    resp = await http.request(
                        method, url, params=query, json=json_body, headers=self._headers
                    )
            except httpx.HTTPError as exc:
                last_exc = exc
                resp = None
                if attempt == attempts - 1:
                    raise QuickBooksApiError(f"Network error calling QuickBooks: {exc}") from exc
            else:
                if resp.status_code == 401:
                    raise QuickBooksAuthError(
                        "QuickBooks rejected the access token.", status_code=401
                    )
                if resp.status_code in _RETRYABLE_STATUS and attempt < attempts - 1:
                    logger.info(
                        "QuickBooks returned retryable %s for %s (attempt %d/%d)",
                        resp.status_code, path, attempt + 1, attempts,
                    )
                elif resp.status_code >= 400:
                    raise QuickBooksApiError(
                        f"QuickBooks API error {resp.status_code} for {path}: {resp.text[:500]}",
                        status_code=resp.status_code,
                    )
                else:
                    try:
                        return resp.json() or {}
                    except ValueError:
                        return {}

            retry_after = resp.headers.get("Retry-After") if resp is not None else None
            if retry_after:
                try:
                    delay = float(retry_after)
                except ValueError:
                    delay = self.retry_base_seconds * (2 ** attempt)
            else:
                delay = self.retry_base_seconds * (2 ** attempt)
            delay = min(delay, _MAX_BACKOFF_SECONDS)
            await asyncio.sleep(random.uniform(0.0, delay) if delay > 0 else 0.0)

        if last_exc:
            raise QuickBooksApiError(f"QuickBooks request failed: {last_exc}") from last_exc
        raise QuickBooksApiError(f"QuickBooks request to {path} failed after {attempts} attempts")

    async def query(self, statement: str) -> dict[str, Any]:
        """Run a QBO SQL-like query and return the ``QueryResponse`` object."""
        body = await self._request("GET", "query", params={"query": statement})
        return body.get("QueryResponse") or {}

    async def list_accounts(self) -> list[dict[str, Any]]:
        """Page through the QBO chart of accounts."""
        accounts: list[dict[str, Any]] = []
        start = 1
        page = 100
        while True:
            response = await self.query(
                f"SELECT * FROM Account STARTPOSITION {start} MAXRESULTS {page}"
            )
            batch = response.get("Account") or []
            accounts.extend(batch)
            if len(batch) < page:
                break
            start += page
        return accounts

    async def find_journal_entry_by_doc_number(self, doc_number: str) -> dict[str, Any] | None:
        """Look up a JournalEntry by DocNumber.

        Used before every push so an entry that landed in QBO during a failed
        request is adopted rather than created a second time.
        """
        safe = doc_number.replace("'", "''")
        response = await self.query(
            f"SELECT * FROM JournalEntry WHERE DocNumber = '{safe}' MAXRESULTS 1"
        )
        entries = response.get("JournalEntry") or []
        return entries[0] if entries else None

    async def create_journal_entry(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = await self._request("POST", "journalentry", json_body=payload)
        return body.get("JournalEntry") or {}

    async def company_info(self) -> dict[str, Any]:
        body = await self._request("GET", f"companyinfo/{self.realm_id}")
        return body.get("CompanyInfo") or {}
