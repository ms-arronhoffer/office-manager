"""Provider contract tests for Portfolio Desk AI integrations."""
from __future__ import annotations

from typing import Any

import pytest

from app.config import settings
from app.services import ai_service


class _Response:
    status_code = 200
    reason_phrase = "OK"

    def __init__(self, body: dict[str, Any]):
        self._body = body

    def json(self) -> dict[str, Any]:
        return self._body


def _configure_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AI_PROVIDER", "openai")
    monkeypatch.setattr(settings, "AI_MODEL", "gpt-test")
    monkeypatch.setattr(settings, "AI_MODEL_FAST", "gpt-fast-test")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "openai-secret")


def test_legacy_configuration_still_selects_gemini(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "")
    monkeypatch.setattr(settings, "AI_MODEL", "")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "gemini-secret")
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-test")

    assert ai_service.get_provider_name() == "gemini"
    assert ai_service.get_model_name() == "gemini-test"
    assert ai_service.is_configured() is True


@pytest.mark.asyncio
async def test_openai_generation_payload_and_usage(monkeypatch: pytest.MonkeyPatch):
    _configure_openai(monkeypatch)
    captured: dict[str, Any] = {}

    async def fake_post(url: str, **kwargs: Any) -> _Response:
        captured.update(url=url, **kwargs)
        return _Response(
            {
                "choices": [{"message": {"content": '{"answer":"ok"}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            }
        )

    monkeypatch.setattr(ai_service, "_post_with_retry", fake_post)
    ai_service.reset_token_usage()

    result = await ai_service._generate(
        [{"text": "Return JSON"}],
        system_instruction="Be precise.",
        json_response=True,
        model="fast",
    )

    assert result == '{"answer":"ok"}'
    assert captured["url"].endswith("/chat/completions")
    assert captured["headers"]["Authorization"] == "Bearer openai-secret"
    assert captured["json"]["model"] == "gpt-fast-test"
    assert captured["json"]["messages"][0]["role"] == "system"
    assert captured["json"]["response_format"] == {"type": "json_object"}
    assert ai_service.collect_token_usage() == (12, 4)


def test_openrouter_attribution_headers(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "openrouter")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "router-secret")
    monkeypatch.setattr(settings, "OPENROUTER_SITE_URL", "https://portfolio.example")
    monkeypatch.setattr(settings, "OPENROUTER_APP_NAME", "Portfolio Desk Test")

    headers = ai_service._openai_headers("openrouter")

    assert headers["Authorization"] == "Bearer router-secret"
    assert headers["HTTP-Referer"] == "https://portfolio.example"
    assert headers["X-Title"] == "Portfolio Desk Test"


def test_openai_content_rejects_non_image_inline_files(
    monkeypatch: pytest.MonkeyPatch,
):
    _configure_openai(monkeypatch)

    with pytest.raises(ai_service.AIDocumentError, match="application/pdf"):
        ai_service._openai_content(
            [{"inlineData": {"mimeType": "application/pdf", "data": "ZmlsZQ=="}}]
        )


@pytest.mark.asyncio
async def test_openai_embeddings_request_768_dimensions(
    monkeypatch: pytest.MonkeyPatch,
):
    _configure_openai(monkeypatch)
    monkeypatch.setattr(settings, "AI_EMBED_PROVIDER", "openai")
    monkeypatch.setattr(settings, "AI_EMBED_MODEL", "text-embedding-3-small")
    monkeypatch.setattr(settings, "AI_EMBED_DIMENSIONS", 768)
    captured: dict[str, Any] = {}

    async def fake_post(url: str, **kwargs: Any) -> _Response:
        captured.update(url=url, **kwargs)
        return _Response(
            {
                "data": [{"index": 0, "embedding": [0.0] * 768}],
                "usage": {"prompt_tokens": 3, "total_tokens": 3},
            }
        )

    monkeypatch.setattr(ai_service, "_post_with_retry", fake_post)

    vectors = await ai_service.embed_texts(["lease termination"])

    assert len(vectors) == 1
    assert len(vectors[0]) == 768
    assert captured["url"].endswith("/embeddings")
    assert captured["json"]["dimensions"] == 768


@pytest.mark.asyncio
async def test_embedding_width_mismatch_fails_closed(monkeypatch: pytest.MonkeyPatch):
    _configure_openai(monkeypatch)
    monkeypatch.setattr(settings, "AI_EMBED_PROVIDER", "openai")
    monkeypatch.setattr(settings, "AI_EMBED_MODEL", "wrong-width-model")
    monkeypatch.setattr(settings, "AI_EMBED_DIMENSIONS", 768)

    async def fake_post(url: str, **kwargs: Any) -> _Response:
        return _Response({"data": [{"index": 0, "embedding": [0.0] * 3}]})

    monkeypatch.setattr(ai_service, "_post_with_retry", fake_post)

    with pytest.raises(ai_service.AIRequestError, match="expected 768"):
        await ai_service.embed_texts(["lease termination"])