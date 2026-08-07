"""Deployment-facing SSO configuration behavior."""
import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.routers import sso
from app.services import sso_service


def test_encrypt_client_secret_returns_actionable_503(monkeypatch):
    def fail(_secret: str) -> str:
        raise RuntimeError("ENCRYPTION_KEY is not configured")

    monkeypatch.setattr(sso, "encrypt_secret", fail)

    with pytest.raises(HTTPException) as exc_info:
        sso._encrypt_client_secret("secret")

    assert exc_info.value.status_code == 503
    assert "ENCRYPTION_KEY" in exc_info.value.detail


def test_encrypt_client_secret_returns_ciphertext(monkeypatch):
    monkeypatch.setattr(sso, "encrypt_secret", lambda secret: f"encrypted:{secret}")

    assert sso._encrypt_client_secret("secret") == "encrypted:secret"


def test_sso_error_preserves_safe_code():
    error = sso_service.SsoError("Account is inactive", code="account_inactive")
    assert error.code == "account_inactive"


def test_sso_error_redirect_clears_existing_session(monkeypatch):
    monkeypatch.setattr(sso.settings, "APP_ENV", "production")

    response = sso._error_redirect("account_inactive")

    assert "sso_error=account_inactive" in response.headers["location"]
    cookies = response.headers.getlist("set-cookie")
    assert any(value.startswith("om_access=") and "Max-Age=0" in value for value in cookies)
    assert any(value.startswith("om_refresh=") and "Max-Age=0" in value for value in cookies)


@pytest.mark.asyncio
async def test_sso_rejection_survives_session_rollback():
    db = AsyncMock()
    error = sso_service.SsoError("Account is inactive", code="account_inactive")

    response = await sso._rollback_sso_rejection(
        db, org_id=uuid.uuid4(), exc=error
    )

    db.rollback.assert_awaited_once()
    assert response.status_code == 302
    assert "sso_error=account_inactive" in response.headers["location"]


def test_extract_first_name_prefers_given_name():
    claims = {"given_name": "  Alexandra  ", "name": "Alexandra Smith"}
    assert sso_service.extract_first_name(claims, "asmith@example.com") == "Alexandra"


def test_extract_first_name_falls_back_to_name_then_email():
    assert (
        sso_service.extract_first_name({"name": "Morgan Lee"}, "mlee@example.com")
        == "Morgan"
    )
    assert sso_service.extract_first_name({}, "casey@example.com") == "casey"
