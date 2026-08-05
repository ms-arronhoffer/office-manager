"""Deployment-facing SSO configuration behavior."""
import pytest
from fastapi import HTTPException

from app.routers import sso


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
