"""Unit tests for the Gemini client resilience + per-task model selection.

Covers plan items #5 (retry/backoff on transient failures) and #12 (a cheaper
"fast" model for low-stakes tasks like intent parsing).
"""
import httpx
import pytest

from app.config import settings
from app.services import ai_service


def test_resolve_model_default():
    assert ai_service._resolve_model(None) == settings.GEMINI_MODEL


def test_resolve_model_literal():
    assert ai_service._resolve_model("gemini-custom-1") == "gemini-custom-1"


def test_resolve_model_fast_falls_back_when_unset(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_MODEL_FAST", "")
    assert ai_service._resolve_model("fast") == settings.GEMINI_MODEL


def test_resolve_model_fast_uses_configured(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_MODEL_FAST", "gemini-flash-lite")
    assert ai_service._resolve_model("fast") == "gemini-flash-lite"


class _FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


class _FakeClient:
    """Stand-in for httpx.AsyncClient that yields a scripted status sequence."""

    calls = 0
    statuses: list[int] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, params=None, json=None):
        idx = type(self).calls
        type(self).calls += 1
        return _FakeResponse(type(self).statuses[idx])


@pytest.mark.asyncio
async def test_post_with_retry_recovers_after_transient(monkeypatch):
    _FakeClient.calls = 0
    _FakeClient.statuses = [503, 200]
    monkeypatch.setattr(settings, "GEMINI_MAX_RETRIES", 2)
    monkeypatch.setattr(settings, "GEMINI_RETRY_BASE_SECONDS", 0.0)
    monkeypatch.setattr(ai_service.httpx, "AsyncClient", _FakeClient)

    resp = await ai_service._post_with_retry(
        "http://x", params={}, json={}
    )
    assert resp.status_code == 200
    assert _FakeClient.calls == 2


@pytest.mark.asyncio
async def test_post_with_retry_gives_up_after_max(monkeypatch):
    _FakeClient.calls = 0
    _FakeClient.statuses = [503, 503, 503]
    monkeypatch.setattr(settings, "GEMINI_MAX_RETRIES", 2)
    monkeypatch.setattr(settings, "GEMINI_RETRY_BASE_SECONDS", 0.0)
    monkeypatch.setattr(ai_service.httpx, "AsyncClient", _FakeClient)

    resp = await ai_service._post_with_retry("http://x", params={}, json={})
    # After exhausting retries the last (still-failing) response is returned.
    assert resp.status_code == 503
    assert _FakeClient.calls == 3


@pytest.mark.asyncio
async def test_post_with_retry_does_not_retry_client_error(monkeypatch):
    _FakeClient.calls = 0
    _FakeClient.statuses = [400, 200]
    monkeypatch.setattr(settings, "GEMINI_MAX_RETRIES", 2)
    monkeypatch.setattr(settings, "GEMINI_RETRY_BASE_SECONDS", 0.0)
    monkeypatch.setattr(ai_service.httpx, "AsyncClient", _FakeClient)

    resp = await ai_service._post_with_retry("http://x", params={}, json={})
    assert resp.status_code == 400
    assert _FakeClient.calls == 1
