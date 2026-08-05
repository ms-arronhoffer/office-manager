"""OIDC helpers for organization single sign-on.

Isolates every outbound call to the identity provider (discovery document,
JWKS, token exchange) plus ID token verification so the router stays thin and
tests can substitute a fake IdP without touching the network.

Security notes:
  - Issuer URLs must be https. Discovery and JWKS documents are fetched only
    from the configured issuer's own origin, which blocks an admin-supplied
    issuer from redirecting metadata lookups at an internal host.
  - ID tokens are verified against the IdP JWKS with ``iss``, ``aud`` and
    ``exp`` enforced; ``nonce`` is checked against the value bound to the
    login state.
  - Nothing here logs tokens, authorization codes, or the client secret.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import time
from urllib.parse import urlparse

import httpx
from jose import jwt as jose_jwt
from jose.exceptions import JWTError

logger = logging.getLogger(__name__)

# Seconds a discovery document / JWKS is reused before being refetched.
_METADATA_TTL_SECONDS = 3600

_HTTP_TIMEOUT_SECONDS = 15.0

# Signature algorithms accepted on an ID token. "none" and the HMAC family are
# deliberately excluded so a token cannot be forged with the client secret.
ALLOWED_ID_TOKEN_ALGORITHMS = ("RS256", "RS384", "RS512", "ES256", "ES384", "ES512")

_metadata_cache: dict[str, tuple[float, dict]] = {}


class SsoError(Exception):
    """Raised when an SSO exchange or verification step fails."""


def clear_metadata_cache() -> None:
    _metadata_cache.clear()


def normalize_issuer(issuer: str) -> str:
    """Validate and canonicalize an issuer URL. Raises ``SsoError`` if unusable."""
    candidate = (issuer or "").strip().rstrip("/")
    parsed = urlparse(candidate)
    if parsed.scheme != "https" or not parsed.netloc:
        raise SsoError("Issuer must be an https URL.")
    if parsed.query or parsed.fragment:
        raise SsoError("Issuer must not contain a query string or fragment.")
    return candidate


def generate_pkce() -> tuple[str, str]:
    """Return an S256 ``(code_verifier, code_challenge)`` pair."""
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def _cache_get(key: str) -> dict | None:
    entry = _metadata_cache.get(key)
    if not entry:
        return None
    expires_at, value = entry
    if expires_at < time.monotonic():
        _metadata_cache.pop(key, None)
        return None
    return value


def _cache_put(key: str, value: dict) -> None:
    _metadata_cache[key] = (time.monotonic() + _METADATA_TTL_SECONDS, value)


async def _get_json(url: str) -> dict:
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS, follow_redirects=False) as client:
        response = await client.get(url)
    if response.status_code != 200:
        raise SsoError(f"Identity provider returned {response.status_code} for {url}")
    try:
        return response.json()
    except ValueError as exc:
        raise SsoError("Identity provider returned a malformed document.") from exc


async def discover(issuer: str) -> dict:
    """Fetch (and cache) the issuer's OpenID Connect discovery document."""
    issuer = normalize_issuer(issuer)
    cache_key = f"discovery:{issuer}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    document = await _get_json(f"{issuer}/.well-known/openid-configuration")

    for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        value = document.get(field)
        if not isinstance(value, str) or not value:
            raise SsoError(f"Discovery document is missing '{field}'.")
        _require_same_origin(issuer, value, field)

    # A provider whose advertised issuer differs from the configured one would
    # make the ID token ``iss`` check unsatisfiable; fail early and loudly.
    advertised = str(document.get("issuer", "")).rstrip("/")
    if advertised and advertised != issuer:
        raise SsoError("Discovery document issuer does not match the configured issuer.")

    _cache_put(cache_key, document)
    return document


def _require_same_origin(issuer: str, url: str, field: str) -> None:
    issuer_host = urlparse(issuer).netloc.lower()
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc.lower() != issuer_host:
        raise SsoError(f"Discovery document '{field}' is not on the issuer's origin.")


async def fetch_jwks(jwks_uri: str) -> dict:
    """Fetch (and cache) the IdP signing keys."""
    cache_key = f"jwks:{jwks_uri}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    jwks = await _get_json(jwks_uri)
    if not isinstance(jwks.get("keys"), list) or not jwks["keys"]:
        raise SsoError("Identity provider returned an empty JWKS.")
    _cache_put(cache_key, jwks)
    return jwks


def build_authorize_url(
    authorization_endpoint: str,
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    nonce: str,
    code_challenge: str,
) -> str:
    from urllib.parse import urlencode

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    separator = "&" if "?" in authorization_endpoint else "?"
    return f"{authorization_endpoint}{separator}{urlencode(params)}"


async def exchange_code(
    token_endpoint: str,
    *,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict:
    """Trade an authorization code for the token response."""
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
        "code_verifier": code_verifier,
    }
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS, follow_redirects=False) as client:
        response = await client.post(
            token_endpoint,
            data=payload,
            headers={"Accept": "application/json"},
        )
    if response.status_code != 200:
        # The body can echo the submitted client_secret, so it is never logged.
        logger.warning("SSO token exchange failed with status %s", response.status_code)
        raise SsoError("Identity provider rejected the authorization code.")
    try:
        tokens = response.json()
    except ValueError as exc:
        raise SsoError("Identity provider returned a malformed token response.") from exc
    if not tokens.get("id_token"):
        raise SsoError("Identity provider did not return an ID token.")
    return tokens


def verify_id_token(id_token: str, *, jwks: dict, issuer: str, client_id: str, nonce: str) -> dict:
    """Verify signature, ``iss``, ``aud``, ``exp`` and ``nonce``; return claims."""
    try:
        claims = jose_jwt.decode(
            id_token,
            jwks,
            algorithms=list(ALLOWED_ID_TOKEN_ALGORITHMS),
            audience=client_id,
            issuer=normalize_issuer(issuer),
            options={"verify_at_hash": False, "require_exp": True},
        )
    except JWTError as exc:
        raise SsoError(f"ID token verification failed: {exc}") from exc

    if claims.get("nonce") != nonce:
        raise SsoError("ID token nonce does not match the login request.")
    if not claims.get("sub"):
        raise SsoError("ID token is missing 'sub'.")
    return claims


def extract_verified_email(claims: dict) -> str:
    """Return the lowercase verified email from ID token claims.

    An unverified address is refused: it would let anyone who can register that
    address at the IdP take over a local account.
    """
    email = claims.get("email")
    if not isinstance(email, str) or "@" not in email:
        raise SsoError("ID token did not include an email address.")
    verified = claims.get("email_verified")
    if verified is False or str(verified).lower() == "false":
        raise SsoError("Identity provider reported the email address as unverified.")
    return email.strip().lower()


def email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].strip().lower()


def normalize_domains(domains: list[str] | None) -> list[str]:
    """Lowercase, de-duplicate, and strip leading '@'/'.' from domain entries."""
    seen: list[str] = []
    for raw in domains or []:
        value = str(raw).strip().lower().lstrip("@.")
        if value and value not in seen:
            seen.append(value)
    return seen


def is_domain_allowed(email: str, allowed_domains: list[str]) -> bool:
    """True when ``email``'s domain exactly matches an allowed domain.

    Subdomains are not implied: an org allowing "contoso.com" does not accept
    "evil.contoso.com" unless that domain is listed too.
    """
    if not allowed_domains:
        return False
    return email_domain(email) in normalize_domains(allowed_domains)
