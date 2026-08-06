from datetime import datetime, timezone

import pytest
from fastapi import Response

from app.auth.jwt_handler import decode_access_token
from app.auth.sessions import set_auth_cookies
from app.config import settings


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    yield


def test_cookie_flags_in_production(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    response = Response()
    set_auth_cookies(response, "access", "refresh")
    cookies = response.headers.getlist("set-cookie")
    assert all("Secure" in value for value in cookies)
    assert "HttpOnly" in next(value for value in cookies if value.startswith("om_access="))
    assert "SameSite=strict" in next(value for value in cookies if value.startswith("om_refresh="))


def test_access_tokens_are_short_lived():
    from app.auth.jwt_handler import create_access_token

    token = create_access_token({"sub": "00000000-0000-0000-0000-000000000001"})
    payload = decode_access_token(token)
    assert payload is not None
    remaining = payload["exp"] - int(datetime.now(timezone.utc).timestamp())
    assert 0 < remaining <= settings.JWT_ACCESS_MINUTES * 60