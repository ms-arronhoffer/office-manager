"""SMTP transport selection: implicit TLS (465) vs STARTTLS (587)."""

import pytest

from app.utils import email_client
from app.config import settings


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "port,expect_use_tls,expect_start_tls",
    [
        (465, True, False),   # implicit TLS — wrapped from the start
        (587, False, True),   # STARTTLS — opportunistic upgrade
    ],
)
async def test_authenticated_tls_mode_matches_port(monkeypatch, port, expect_use_tls, expect_start_tls):
    captured: dict = {}

    async def fake_send(message, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(email_client.aiosmtplib, "send", fake_send)
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "SMTP_PORT", port)
    monkeypatch.setattr(settings, "SMTP_USER", "user@example.com")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "secret")

    assert await email_client.send_email("to@x.com", "Hi", "<p>x</p>") is True
    assert captured["use_tls"] is expect_use_tls
    assert captured["start_tls"] is expect_start_tls


@pytest.mark.asyncio
async def test_unconfigured_smtp_skips(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "")
    assert await email_client.send_email("to@x.com", "Hi", "<p>x</p>") is False
