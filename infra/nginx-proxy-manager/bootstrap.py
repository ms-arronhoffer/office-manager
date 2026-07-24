#!/usr/bin/env python3
"""Idempotently configure Nginx Proxy Manager (NPM) for the Office Manager stack.

NPM keeps its proxy hosts, certificates and settings in its own SQLite/MySQL
database, so it cannot be configured purely declaratively from the compose
file. This script talks to the NPM admin API (default ``http://localhost:81``)
and provisions one proxy host per public domain, each pointing at the
corresponding container over the shared ``edge`` docker network:

    frontend domain -> http://frontend:80
    admin domain    -> http://admin-frontend:80
    landing domain  -> http://landing:80
    api domain      -> http://backend:8000   (optional)

Every proxy host is created with:

  * a Let's Encrypt certificate (requested/reused automatically),
  * "Block Common Exploits" enabled  (block_exploits),
  * "Websockets Support" enabled     (allow_websocket_upgrade),
  * "Force SSL" + HSTS + HTTP/2 enabled (ssl_forced / hsts_enabled / http2).

The script is idempotent: existing proxy hosts (matched by domain) are updated
in place and existing Let's Encrypt certificates are reused, so it is safe to
run on every deploy.

Configuration is entirely environment-driven — see ``infra/nginx-proxy-manager/
README.md`` and ``.env.example``. Only routes whose domain variable is set are
provisioned, so a partial configuration is fine.

Uses the Python standard library only (no third-party dependencies).
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


class NpmError(RuntimeError):
    """Raised when the NPM API returns an unexpected response."""


@dataclass
class Route:
    """A desired public route -> internal container mapping."""

    name: str
    domain: str
    forward_host: str
    forward_port: int


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _api(
    base_url: str,
    method: str,
    path: str,
    token: str | None = None,
    payload: dict | None = None,
) -> object:
    """Make a JSON request against the NPM API and return the parsed body."""

    url = f"{base_url.rstrip('/')}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode()
    except urllib.error.HTTPError as exc:  # pragma: no cover - network dependent
        detail = exc.read().decode(errors="replace")
        raise NpmError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:  # pragma: no cover - network dependent
        raise NpmError(f"{method} {path} failed: {exc.reason}") from exc
    if not body:
        return None
    return json.loads(body)


def _wait_for_api(base_url: str, attempts: int = 30, delay: int = 5) -> None:
    """Block until the NPM API responds (it is slow to come up on first boot)."""

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            _api(base_url, "GET", "/api/")
            return
        except NpmError as exc:  # pragma: no cover - network dependent
            last_error = exc
            print(f"  NPM API not ready (attempt {attempt}/{attempts}); retrying in {delay}s…")
            time.sleep(delay)
    raise NpmError(f"NPM API never became reachable at {base_url}: {last_error}")


def _login(base_url: str, identity: str, secret: str) -> str:
    result = _api(base_url, "POST", "/api/tokens", payload={"identity": identity, "secret": secret})
    if not isinstance(result, dict) or "token" not in result:
        raise NpmError("Login did not return a token; check NPM admin credentials.")
    return str(result["token"])


def _find_certificate(base_url: str, token: str, domain: str) -> int | None:
    """Return the id of an existing Let's Encrypt cert covering ``domain``."""

    certs = _api(base_url, "GET", "/api/nginx/certificates", token=token)
    if not isinstance(certs, list):
        return None
    for cert in certs:
        if domain in (cert.get("domain_names") or []):
            return int(cert["id"])
    return None


def _ensure_certificate(base_url: str, token: str, domain: str, email: str) -> int | None:
    """Reuse or request a Let's Encrypt certificate for ``domain``.

    Returns the certificate id, or ``None`` if issuance failed (e.g. DNS not yet
    pointed at the host / port 80 unreachable). A ``None`` result is tolerated so
    the proxy host is still created and the script can be re-run once DNS is live.
    """

    existing = _find_certificate(base_url, token, domain)
    if existing is not None:
        print(f"    reusing existing certificate #{existing} for {domain}")
        return existing

    print(f"    requesting Let's Encrypt certificate for {domain}…")
    payload = {
        "domain_names": [domain],
        "meta": {
            "letsencrypt_email": email,
            "letsencrypt_agree": True,
            "dns_challenge": False,
        },
        "provider": "letsencrypt",
    }
    try:
        created = _api(base_url, "POST", "/api/nginx/certificates", token=token, payload=payload)
    except NpmError as exc:
        print(f"    WARNING: certificate issuance failed for {domain}: {exc}")
        print("    Proxy host will be created without SSL; re-run once DNS/port 80 are reachable.")
        return None
    if isinstance(created, dict) and "id" in created:
        print(f"    issued certificate #{created['id']} for {domain}")
        return int(created["id"])
    return None


def _proxy_host_payload(route: Route, certificate_id: int | None) -> dict:
    """Build the NPM proxy-host body with the required hardening toggles."""

    ssl_enabled = certificate_id is not None
    return {
        "domain_names": [route.domain],
        "forward_scheme": "http",
        "forward_host": route.forward_host,
        "forward_port": route.forward_port,
        "access_list_id": 0,
        "certificate_id": certificate_id if ssl_enabled else 0,
        # Hardening / feature toggles requested for every route:
        "block_exploits": True,           # "Block Common Exploits"
        "allow_websocket_upgrade": True,  # "Websockets Support"
        "caching_enabled": False,
        "ssl_forced": ssl_enabled,        # "Force SSL" (only when a cert exists)
        "hsts_enabled": ssl_enabled,
        "hsts_subdomains": False,
        "http2_support": ssl_enabled,
        "advanced_config": "",
        "enabled": True,
        "meta": {"letsencrypt_agree": True, "dns_challenge": False},
        "locations": [],
    }


def _existing_proxy_host(base_url: str, token: str, domain: str) -> dict | None:
    hosts = _api(base_url, "GET", "/api/nginx/proxy-hosts", token=token)
    if not isinstance(hosts, list):
        return None
    for host in hosts:
        if domain in (host.get("domain_names") or []):
            return host
    return None


def _ensure_proxy_host(base_url: str, token: str, route: Route, email: str) -> None:
    print(f"  {route.name}: {route.domain} -> http://{route.forward_host}:{route.forward_port}")
    certificate_id = _ensure_certificate(base_url, token, route.domain, email) if email else None
    if not email:
        print("    NPM_LETSENCRYPT_EMAIL unset; skipping SSL (route served over HTTP only).")
    payload = _proxy_host_payload(route, certificate_id)

    existing = _existing_proxy_host(base_url, token, route.domain)
    if existing is not None:
        host_id = int(existing["id"])
        _api(base_url, "PUT", f"/api/nginx/proxy-hosts/{host_id}", token=token, payload=payload)
        print(f"    updated proxy host #{host_id}")
    else:
        created = _api(base_url, "POST", "/api/nginx/proxy-hosts", token=token, payload=payload)
        host_id = created["id"] if isinstance(created, dict) else "?"
        print(f"    created proxy host #{host_id}")


def _build_routes() -> list[Route]:
    """Collect the routes whose domain env vars are set."""

    specs = [
        ("frontend", "NPM_FRONTEND_DOMAIN", "frontend", 80),
        ("admin", "NPM_ADMIN_DOMAIN", "admin-frontend", 80),
        ("landing", "NPM_LANDING_DOMAIN", "landing", 80),
        ("api", "NPM_API_DOMAIN", "backend", 8000),
    ]
    routes: list[Route] = []
    for name, env_var, host, port in specs:
        domain = _env(env_var)
        if domain:
            routes.append(Route(name=name, domain=domain, forward_host=host, forward_port=port))
    return routes


def main() -> int:
    base_url = _env("NPM_BASE_URL", "http://localhost:81")
    identity = _env("NPM_ADMIN_EMAIL", "admin@example.com")
    secret = _env("NPM_ADMIN_PASSWORD", "changeme")
    letsencrypt_email = _env("NPM_LETSENCRYPT_EMAIL")

    routes = _build_routes()
    if not routes:
        print(
            "No NPM_*_DOMAIN variables set — nothing to configure. Set at least one of "
            "NPM_FRONTEND_DOMAIN / NPM_ADMIN_DOMAIN / NPM_LANDING_DOMAIN / NPM_API_DOMAIN.",
            file=sys.stderr,
        )
        return 1

    print(f"Configuring Nginx Proxy Manager at {base_url}")
    _wait_for_api(base_url)
    token = _login(base_url, identity, secret)
    print("Authenticated with NPM admin API.")

    for route in routes:
        _ensure_proxy_host(base_url, token, route, letsencrypt_email)

    print("Done. Proxy hosts configured with Block Common Exploits, Websockets Support and Force SSL.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
