"""Tests for the NPM bootstrap first-boot credential self-provisioning."""

from __future__ import annotations

import importlib.util
import io
import sys
import unittest
import urllib.error
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "npm_bootstrap", Path(__file__).with_name("bootstrap.py")
)
bootstrap = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
sys.modules["npm_bootstrap"] = bootstrap
_SPEC.loader.exec_module(bootstrap)


def _http_error(code: int, body: str = "") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="http://localhost:81/api/tokens",
        code=code,
        msg="err",
        hdrs=None,
        fp=io.BytesIO(body.encode()),
    )


class FakeNpm:
    """Minimal in-memory stand-in for the NPM admin API used by bootstrap._api."""

    def __init__(self, email: str | None, password: str | None, *, has_user: bool = True) -> None:
        # ``has_user=False`` models a brand-new NPM (>= 2.12): no admin account
        # exists yet and ``GET /api/`` reports ``setup: false``.
        self.email = email
        self.password = password
        self.has_user = has_user and email is not None
        self.user_id = 1
        self.calls: list[tuple[str, str]] = []

    def api(self, base_url, method, path, token=None, payload=None):  # noqa: ARG002
        self.calls.append((method, path))
        if method == "GET" and path == "/api/":
            return {"status": "OK", "setup": self.has_user}
        if method == "POST" and path == "/api/tokens":
            if (
                self.has_user
                and payload["identity"] == self.email
                and payload["secret"] == self.password
            ):
                return {"token": "tok", "expires": "later"}
            raise bootstrap.NpmAuthError("POST /api/tokens -> HTTP 400: bad creds")
        if method == "POST" and path == "/api/users":
            # Fresh-install first-admin creation is unauthenticated.
            assert not self.has_user
            self.email = payload["email"]
            self.password = payload["auth"]["secret"]
            self.has_user = True
            return {"id": self.user_id, "email": self.email}
        if method == "GET" and path == "/api/users/me":
            return {"id": self.user_id, "email": self.email, "name": "Administrator"}
        if method == "PUT" and path == f"/api/users/{self.user_id}":
            self.email = payload["email"]
            return {"id": self.user_id, "email": self.email}
        if method == "PUT" and path == f"/api/users/{self.user_id}/auth":
            assert payload["current"] == self.password
            self.password = payload["secret"]
            return True
        raise AssertionError(f"unexpected call {method} {path}")


class LoginTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_api = bootstrap._api

    def tearDown(self) -> None:
        bootstrap._api = self._orig_api

    def test_login_with_matching_credentials(self) -> None:
        fake = FakeNpm("ops@corp.com", "sup3rsecret")
        bootstrap._api = fake.api
        token = bootstrap._login("http://localhost:81", "ops@corp.com", "sup3rsecret")
        self.assertEqual(token, "tok")
        # No provisioning calls when the configured creds already work.
        self.assertNotIn(("GET", "/api/users/me"), fake.calls)

    def test_first_boot_provisions_configured_credentials(self) -> None:
        fake = FakeNpm(bootstrap.DEFAULT_ADMIN_EMAIL, bootstrap.DEFAULT_ADMIN_PASSWORD)
        bootstrap._api = fake.api
        token = bootstrap._login("http://localhost:81", "ops@corp.com", "sup3rsecret")
        self.assertEqual(token, "tok")
        # The seeded default account was rotated to the configured credentials.
        self.assertEqual(fake.email, "ops@corp.com")
        self.assertEqual(fake.password, "sup3rsecret")
        self.assertIn(("PUT", "/api/users/1"), fake.calls)
        self.assertIn(("PUT", "/api/users/1/auth"), fake.calls)

    def test_fresh_install_creates_first_admin(self) -> None:
        # Modern NPM (>= 2.12) starts with no users and reports setup:false;
        # the first admin is created with the configured credentials directly.
        fake = FakeNpm(None, None, has_user=False)
        bootstrap._api = fake.api
        token = bootstrap._login("http://localhost:81", "ops@corp.com", "sup3rsecret")
        self.assertEqual(token, "tok")
        self.assertEqual(fake.email, "ops@corp.com")
        self.assertEqual(fake.password, "sup3rsecret")
        self.assertIn(("POST", "/api/users"), fake.calls)
        # No legacy default-credential rotation is attempted.
        self.assertNotIn(("PUT", "/api/users/1/auth"), fake.calls)

    def test_default_credentials_rejected_raises(self) -> None:
        fake = FakeNpm("someone@else.com", "unknownpass")
        bootstrap._api = fake.api
        with self.assertRaises(bootstrap.NpmError):
            bootstrap._login("http://localhost:81", "ops@corp.com", "sup3rsecret")

    def test_configured_default_credentials_rejected_raises(self) -> None:
        # Configured creds *are* the defaults but NPM rejects them.
        fake = FakeNpm("someone@else.com", "unknownpass")
        bootstrap._api = fake.api
        with self.assertRaises(bootstrap.NpmError):
            bootstrap._login(
                "http://localhost:81",
                bootstrap.DEFAULT_ADMIN_EMAIL,
                bootstrap.DEFAULT_ADMIN_PASSWORD,
            )


class ApiErrorTests(unittest.TestCase):
    def test_401_raises_auth_error(self) -> None:
        def fake_urlopen(req, timeout=0):  # noqa: ARG001
            raise _http_error(401, "unauthorized")

        orig = bootstrap.urllib.request.urlopen
        bootstrap.urllib.request.urlopen = fake_urlopen
        try:
            with self.assertRaises(bootstrap.NpmAuthError):
                bootstrap._api("http://localhost:81", "POST", "/api/tokens", payload={})
        finally:
            bootstrap.urllib.request.urlopen = orig

    def test_500_raises_plain_error(self) -> None:
        def fake_urlopen(req, timeout=0):  # noqa: ARG001
            raise _http_error(500, "boom")

        orig = bootstrap.urllib.request.urlopen
        bootstrap.urllib.request.urlopen = fake_urlopen
        try:
            with self.assertRaises(bootstrap.NpmError) as ctx:
                bootstrap._api("http://localhost:81", "GET", "/api/")
            self.assertNotIsInstance(ctx.exception, bootstrap.NpmAuthError)
        finally:
            bootstrap.urllib.request.urlopen = orig

    def test_malformed_http_response_raises_transient_error(self) -> None:
        # NPM can emit a partial/malformed HTTP response while booting, which
        # urllib surfaces as an ``http.client.HTTPException`` (not an OSError or
        # URLError). It must be wrapped as an NpmError so ``_wait_for_api`` can
        # retry instead of crashing the deploy.
        import http.client

        def fake_urlopen(req, timeout=0):  # noqa: ARG001
            raise http.client.BadStatusLine("''")

        orig = bootstrap.urllib.request.urlopen
        bootstrap.urllib.request.urlopen = fake_urlopen
        try:
            with self.assertRaises(bootstrap.NpmError):
                bootstrap._api("http://localhost:81", "GET", "/api/")
        finally:
            bootstrap.urllib.request.urlopen = orig


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
