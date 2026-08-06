"""Deployment-facing SSO configuration behavior."""
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


def test_extract_first_name_prefers_given_name():
    claims = {"given_name": "  Alexandra  ", "name": "Alexandra Smith"}
    assert sso_service.extract_first_name(claims, "asmith@example.com") == "Alexandra"


def test_extract_first_name_falls_back_to_name_then_email():
    assert (
        sso_service.extract_first_name({"name": "Morgan Lee"}, "mlee@example.com")
        == "Morgan"
    )
    assert sso_service.extract_first_name({}, "casey@example.com") == "casey"
