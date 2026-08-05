"""Google Gemini integration for Portfolio Desk AI-assist features.

This is a thin async client over the Gemini ``generateContent`` REST endpoint.
It deliberately avoids a heavy vendored SDK and instead uses ``httpx`` (already a
project dependency) so the model id, API key, and base endpoint stay fully
configurable through environment variables (``GEMINI_MODEL``, ``GEMINI_API_KEY``,
``GEMINI_API_BASE``).

Design notes:

* **Graceful degradation** — when ``GEMINI_API_KEY`` is unset every public
  helper raises :class:`AIUnavailableError`, which the router translates into a
  clear ``503``. Nothing crashes and no network call is attempted. This mirrors
  how SMTP/Stripe degrade elsewhere in the codebase.
* **Structured output** — extraction helpers ask Gemini for JSON
  (``responseMimeType: application/json``) and parse it defensively so the
  result maps cleanly onto existing Pydantic schemas.
* **Async + bounded** — calls run through an async ``httpx`` client with a
  configurable timeout so request worker threads are never blocked indefinitely.

All helpers return *suggestions* for human review; callers never auto-commit
AI output.
"""
from __future__ import annotations

import asyncio
import base64
import contextvars
import hashlib
import json
import logging
from collections import OrderedDict
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Hard caps to protect against oversized prompts / documents.
MAX_DOCUMENT_BYTES = 15 * 1024 * 1024  # 15 MB of raw document bytes per call
MAX_TEXT_CHARS = 200_000

# ── Large-document strategy ──────────────────────────────────────────────────
#
# Uploads are accepted up to ``settings.AI_MAX_FILE_SIZE_MB`` (75 MB by default)
# — far more than a single Gemini request can carry inline. Anything above the
# per-call ceilings above is therefore processed as an ordered series of
# *segments*:
#
# 1. **Text-bearing documents** (Word/text, and PDFs with a text layer) are
#    extracted to plain text locally and split into overlapping chunks of
#    ``MAX_TEXT_CHARS``. Text is dramatically cheaper and faster than shipping
#    raw bytes, so this is always preferred when a usable text layer exists.
# 2. **Scanned / image-only PDFs** have no text to extract, so the PDF itself is
#    split into page ranges that each fit inside ``MAX_DOCUMENT_BYTES`` and sent
#    inline.
#
# Each segment is sent to the model with the same instructions, and the
# per-segment results are merged (see ``_merge_segment_results``) so a value that
# only appears on page 180 still lands in the populated output. Segment count is
# bounded so one upload can never fan out into unbounded provider spend.
MAX_DOCUMENT_SEGMENTS = 8
SEGMENT_OVERLAP_CHARS = 2_000
MAX_SEGMENT_CONCURRENCY = 3
# Ceiling on locally extracted text for the AI pipeline — enough to fill every
# segment, and far above document_extraction's default (search-index) limit.
MAX_AI_EXTRACTED_CHARS = MAX_DOCUMENT_SEGMENTS * MAX_TEXT_CHARS
# Below this many characters a PDF is treated as having no usable text layer
# (i.e. scanned images) and its pages are sent to the model instead.
MIN_USABLE_PDF_TEXT_CHARS = 500
MIN_USABLE_PDF_PAGE_ALNUM_CHARS = 50
MIN_USABLE_PDF_PAGE_COVERAGE = 0.75

# Bump whenever a parse prompt/field-spec changes so cached results from an
# older prompt version are invalidated rather than served stale.
PROMPT_VERSION = "3"

# ── Per-request token accounting ──────────────────────────────────────────────
#
# Gemini returns ``usageMetadata`` with prompt (input) and candidate (output)
# token counts. We accumulate these per request in a ``ContextVar`` so the
# router can read the total tokens spent across however many model calls an
# endpoint made (e.g. an AI feature that calls ``_generate`` once, or embeddings
# plus a generation) without threading return values through every helper. The
# router resets the accumulator at the start of each request and collects the
# total when recording the usage event.

_token_usage_var: contextvars.ContextVar[list[int] | None] = contextvars.ContextVar(
    "ai_token_usage", default=None
)


def reset_token_usage() -> None:
    """Start a fresh token-usage accumulator for the current request context."""
    _token_usage_var.set([0, 0])


def record_token_usage(input_tokens: int, output_tokens: int) -> None:
    """Add provider-reported token counts to the current accumulator."""
    acc = _token_usage_var.get()
    if acc is None:
        acc = [0, 0]
        _token_usage_var.set(acc)
    acc[0] += max(int(input_tokens or 0), 0)
    acc[1] += max(int(output_tokens or 0), 0)


def collect_token_usage() -> tuple[int, int]:
    """Return ``(input_tokens, output_tokens)`` accumulated this request."""
    acc = _token_usage_var.get()
    if acc is None:
        return (0, 0)
    return (acc[0], acc[1])


def _record_usage_metadata(data: dict[str, Any]) -> None:
    """Extract token counts from Gemini or OpenAI-compatible responses."""
    usage = data.get("usage") or {}
    if usage:
        try:
            record_token_usage(
                int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0),
                int(usage.get("completion_tokens") or usage.get("output_tokens") or 0),
            )
        except (TypeError, ValueError):  # pragma: no cover - defensive
            pass
        return

    meta = data.get("usageMetadata") or {}
    prompt_tokens = meta.get("promptTokenCount") or 0
    # Embedding/older responses may omit candidates; fall back to total - prompt.
    candidate_tokens = meta.get("candidatesTokenCount")
    if candidate_tokens is None:
        total = meta.get("totalTokenCount") or 0
        candidate_tokens = max(total - prompt_tokens, 0)
    try:
        record_token_usage(int(prompt_tokens), int(candidate_tokens))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        pass


# ── Response cache (document parses) ──────────────────────────────────────────
#
# Document extraction is deterministic enough that re-parsing the *same* bytes
# with the *same* prompt is wasted latency and Gemini spend. We keep a small,
# in-process LRU cache keyed on a hash of (parser, prompt version, model,
# document bytes / extracted text). The cache is best-effort: it never changes
# behaviour, only short-circuits an identical repeat call within a single
# process. It deliberately stores only parsed JSON (no raw document bytes).

CACHE_MAX_ENTRIES = 256
_parse_cache: "OrderedDict[str, dict[str, Any]]" = OrderedDict()


def _cache_key(parser: str, payload: bytes) -> str:
    digest = hashlib.sha256(payload).hexdigest()
    return f"{parser}:{PROMPT_VERSION}:{get_provider_name()}:{get_model_name()}:{digest}"


def _cache_get(key: str) -> dict[str, Any] | None:
    value = _parse_cache.get(key)
    if value is not None:
        _parse_cache.move_to_end(key)
        # Return a copy so callers can't mutate the cached object.
        return dict(value)
    return None


def _cache_put(key: str, value: dict[str, Any]) -> None:
    _parse_cache[key] = dict(value)
    _parse_cache.move_to_end(key)
    while len(_parse_cache) > CACHE_MAX_ENTRIES:
        _parse_cache.popitem(last=False)


def _cache_payload(content: bytes, text_content: str | None) -> bytes:
    """Build the bytes a cache key hashes over for a document parse."""
    if text_content is not None:
        return text_content.encode("utf-8", "ignore")
    return content


def clear_parse_cache() -> None:
    """Empty the in-process parse cache (used by tests)."""
    _parse_cache.clear()


class AIError(Exception):
    """Base class for AI-assist failures."""


class AIUnavailableError(AIError):
    """Raised when the AI provider is not configured (no API key)."""


class AIRequestError(AIError):
    """Raised when the provider call fails or returns an unusable response."""


class AIDocumentError(AIError):
    """Raised when the *uploaded document itself* cannot be processed.

    Unlike :class:`AIRequestError` (an upstream failure) this is a client-side
    problem — e.g. an image far larger than a single model call can carry, or a
    PDF that cannot be split — so the router surfaces it as a ``400``.
    """


SUPPORTED_PROVIDERS = frozenset({"gemini", "openai", "openrouter"})


def get_provider_name() -> str:
    """Return the selected generation provider.

    An empty ``AI_PROVIDER`` preserves the original Gemini-only configuration
    contract so existing deployments continue to work without environment
    changes.
    """
    configured = settings.AI_PROVIDER.strip().lower()
    return configured or "gemini"


def get_embedding_provider_name() -> str:
    return settings.AI_EMBED_PROVIDER.strip().lower() or get_provider_name()


def _provider_api_key(provider: str) -> str:
    if provider == "gemini":
        return settings.GEMINI_API_KEY
    if provider == "openai":
        return settings.OPENAI_API_KEY
    if provider == "openrouter":
        return settings.OPENROUTER_API_KEY
    return ""


def is_configured() -> bool:
    """Return whether the selected generation provider is configured."""
    provider = get_provider_name()
    return provider in SUPPORTED_PROVIDERS and bool(_provider_api_key(provider)) and bool(
        get_model_name()
    )


def embeddings_configured() -> bool:
    provider = get_embedding_provider_name()
    return provider in SUPPORTED_PROVIDERS and bool(_provider_api_key(provider)) and bool(
        get_embedding_model_name()
    )


def get_model_name(model: str | None = None) -> str:
    provider = get_provider_name()
    if provider == "gemini":
        default_model = settings.AI_MODEL or settings.GEMINI_MODEL
        fast_model = settings.AI_MODEL_FAST or settings.GEMINI_MODEL_FAST
    else:
        default_model = settings.AI_MODEL
        fast_model = settings.AI_MODEL_FAST
    if model is None:
        return default_model
    if model == "fast":
        return fast_model or default_model
    return model


def get_embedding_model_name() -> str:
    if settings.AI_EMBED_MODEL:
        return settings.AI_EMBED_MODEL
    if get_embedding_provider_name() == "gemini":
        return settings.GEMINI_EMBED_MODEL
    return ""


def _resolve_model(model: str | None) -> str:
    """Resolve a caller-supplied model name to the selected provider model.

    ``None`` selects the default ``GEMINI_MODEL``. The sentinel ``"fast"``
    selects ``GEMINI_MODEL_FAST`` when configured (for cheap, low-stakes tasks
    like intent parsing), transparently falling back to ``GEMINI_MODEL`` when no
    fast model is set so behaviour is unchanged by default.
    """
    return get_model_name(model)


def _endpoint(model: str | None = None) -> str:
    provider = get_provider_name()
    if provider == "gemini":
        base = settings.GEMINI_API_BASE.rstrip("/")
        return f"{base}/models/{_resolve_model(model)}:generateContent"
    if provider == "openai":
        return f"{settings.OPENAI_API_BASE.rstrip('/')}/chat/completions"
    if provider == "openrouter":
        return f"{settings.OPENROUTER_API_BASE.rstrip('/')}/chat/completions"
    raise AIUnavailableError(f"Unsupported AI provider: {provider}")


# HTTP statuses worth retrying: rate limiting + transient server errors.
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


async def _post_with_retry(
    url: str,
    *,
    json: dict[str, Any],
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """POST to an AI provider with bounded, jittered exponential backoff.

    Retries only transient failures — network/timeout errors and ``429``/``5xx``
    responses — since generate and embed calls are idempotent. Non-retryable
    responses (e.g. ``400``/``403``) are returned immediately for the caller to
    surface. Raises the last :class:`httpx.HTTPError` if every attempt fails to
    get a response.
    """
    import asyncio
    import random

    legacy_gemini = not settings.AI_PROVIDER.strip()
    max_retries = settings.GEMINI_MAX_RETRIES if legacy_gemini else settings.AI_MAX_RETRIES
    base_seconds = (
        settings.GEMINI_RETRY_BASE_SECONDS
        if legacy_gemini
        else settings.AI_RETRY_BASE_SECONDS
    )
    timeout_seconds = (
        settings.GEMINI_TIMEOUT_SECONDS if legacy_gemini else settings.AI_TIMEOUT_SECONDS
    )
    attempts = max(0, max_retries) + 1
    base_delay = max(0.0, base_seconds)
    last_exc: httpx.HTTPError | None = None

    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                request_kwargs: dict[str, Any] = {"json": json}
                if params is not None:
                    request_kwargs["params"] = params
                if headers is not None:
                    request_kwargs["headers"] = headers
                resp = await client.post(url, **request_kwargs)
        except httpx.HTTPError as exc:  # network / timeout
            last_exc = exc
            if attempt == attempts - 1:
                raise
        else:
            if resp.status_code in _RETRYABLE_STATUS and attempt < attempts - 1:
                logger.info(
                    "AI provider returned retryable %s (attempt %d/%d); backing off",
                    resp.status_code, attempt + 1, attempts,
                )
            else:
                return resp

        # Exponential backoff with full jitter before the next attempt.
        delay = base_delay * (2 ** attempt)
        await asyncio.sleep(random.uniform(0.0, delay) if delay > 0 else 0.0)

    # Only reached when every attempt raised a network error.
    raise last_exc  # type: ignore[misc]


def _require_configured() -> None:
    if not is_configured():
        provider = get_provider_name()
        raise AIUnavailableError(
            f"AI assist is not configured for provider '{provider}'. "
            "Set AI_PROVIDER, AI_MODEL, and the matching provider API key."
        )


def _openai_headers(provider: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {_provider_api_key(provider)}",
        "Content-Type": "application/json",
    }
    if provider == "openrouter":
        if settings.OPENROUTER_SITE_URL:
            headers["HTTP-Referer"] = settings.OPENROUTER_SITE_URL
        if settings.OPENROUTER_APP_NAME:
            headers["X-Title"] = settings.OPENROUTER_APP_NAME
    return headers


def _openai_content(parts: list[dict[str, Any]]) -> str | list[dict[str, Any]]:
    """Translate canonical Gemini-style parts to OpenAI-compatible content."""
    content: list[dict[str, Any]] = []
    for part in parts:
        if "text" in part:
            content.append({"type": "text", "text": str(part.get("text") or "")})
            continue
        inline = part.get("inlineData") or {}
        mime_type = str(inline.get("mimeType") or "application/octet-stream")
        data = str(inline.get("data") or "")
        if mime_type.startswith("image/"):
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{data}"},
                }
            )
            continue
        raise AIDocumentError(
            f"The selected provider cannot process inline {mime_type} documents. "
            "Use a text-bearing document or configure Gemini for scanned PDFs."
        )
    if all(item["type"] == "text" for item in content):
        return "\n".join(str(item["text"]) for item in content)
    return content


async def _generate(
    parts: list[dict[str, Any]],
    *,
    system_instruction: str | None = None,
    json_response: bool = False,
    temperature: float = 0.2,
    model: str | None = None,
) -> str:
    """Call Gemini ``generateContent`` and return the first text part.

    ``parts`` is the list of content parts (text and/or inline document data).
    ``model`` selects the Gemini model: ``None`` uses ``GEMINI_MODEL`` and the
    sentinel ``"fast"`` uses ``GEMINI_MODEL_FAST`` (falling back to the default
    when unset) for cheap, low-stakes calls such as intent parsing.
    """
    _require_configured()

    provider = get_provider_name()
    if provider == "gemini":
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": temperature},
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        if json_response:
            payload["generationConfig"]["responseMimeType"] = "application/json"
        params = {"key": settings.GEMINI_API_KEY}
        headers = None
    else:
        messages: list[dict[str, Any]] = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": _openai_content(parts)})
        payload = {
            "model": _resolve_model(model),
            "messages": messages,
            "temperature": temperature,
        }
        if json_response:
            payload["response_format"] = {"type": "json_object"}
        params = None
        headers = _openai_headers(provider)

    url = _endpoint(model)
    try:
        resp = await _post_with_retry(
            url,
            params=params,
            headers=headers,
            json=payload,
        )
    except httpx.HTTPError as exc:  # network/timeout after retries
        logger.warning("AI provider request failed: %s", exc)
        raise AIRequestError(f"AI provider request failed: {exc}") from exc

    if resp.status_code != 200:
        # Avoid leaking the API key; surface only the status + provider message.
        detail = _safe_error_detail(resp)
        logger.warning("AI provider returned %s: %s", resp.status_code, detail)
        raise AIRequestError(f"AI provider error ({resp.status_code}): {detail}")

    try:
        data = resp.json()
        if provider == "gemini":
            candidates = data.get("candidates") or []
            first = candidates[0]
            out_parts = first["content"]["parts"]
            text = "".join(p.get("text", "") for p in out_parts)
        else:
            text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as exc:
        logger.warning("Unexpected AI provider response shape: %s", exc)
        raise AIRequestError("AI provider returned an unexpected response") from exc

    _record_usage_metadata(data)

    if not text.strip():
        raise AIRequestError("AI provider returned an empty response")
    return text


def _safe_error_detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        msg = body.get("error", {}).get("message")
        if msg:
            return str(msg)
    except ValueError:
        pass
    return resp.reason_phrase or "unknown error"


def _parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from a model response, tolerating code fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Strip ```json ... ``` fences if the model added them.
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise AIRequestError("AI provider did not return valid JSON") from exc
    if not isinstance(result, dict):
        raise AIRequestError("AI provider returned JSON that was not an object")
    return result


def _document_part(content: bytes, mime_type: str) -> dict[str, Any]:
    if len(content) > MAX_DOCUMENT_BYTES:
        raise AIRequestError(
            f"Document is too large for AI processing "
            f"(max {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB)."
        )
    return {
        "inlineData": {
            "mimeType": mime_type,
            "data": base64.b64encode(content).decode("ascii"),
        }
    }


# ── Large-document segmentation ──────────────────────────────────────────────

def _split_text(text: str) -> list[str]:
    """Split document text into ordered, slightly overlapping model-sized chunks.

    Consecutive chunks overlap by ``SEGMENT_OVERLAP_CHARS`` so a clause that
    straddles a boundary is still seen whole by at least one call.
    """
    clean = (text or "").strip()
    if not clean:
        return []
    if len(clean) <= MAX_TEXT_CHARS:
        return [clean]
    step = MAX_TEXT_CHARS - SEGMENT_OVERLAP_CHARS
    chunks: list[str] = []
    start = 0
    while start < len(clean) and len(chunks) < MAX_DOCUMENT_SEGMENTS:
        chunks.append(clean[start : start + MAX_TEXT_CHARS])
        start += step
    return chunks


async def _extract_pdf_text(content: bytes) -> str:
    """Best-effort local text extraction (empty for scanned or sparse layers).

    Runs in a worker thread: parsing a multi-hundred-page PDF is CPU-bound and
    must not block the event loop.
    """
    from app.services import document_extraction

    try:
        pages = await asyncio.to_thread(document_extraction.extract_pdf_pages, content)
    except document_extraction.DocumentExtractionError as exc:
        logger.info("PDF text extraction failed, falling back to page split: %s", exc)
        return ""
    usable_pages = sum(
        1
        for page in pages
        if sum(character.isalnum() for character in page)
        >= MIN_USABLE_PDF_PAGE_ALNUM_CHARS
    )
    coverage = usable_pages / len(pages) if pages else 0.0
    text = "\n\n".join(page for page in pages if page.strip())
    if (
        len(text.strip()) < MIN_USABLE_PDF_TEXT_CHARS
        or coverage < MIN_USABLE_PDF_PAGE_COVERAGE
    ):
        logger.info(
            "PDF has no usable text layer (%d/%d readable pages); using AI transcription",
            usable_pages,
            len(pages),
        )
        return ""
    return text[:MAX_AI_EXTRACTED_CHARS].strip()


async def _split_large_pdf(content: bytes, mime_type: str) -> list[list[dict[str, Any]]]:
    """Segment an oversized PDF into inline page-range parts (off the event loop)."""
    from app.services import document_extraction

    try:
        blobs = await asyncio.to_thread(
            document_extraction.split_pdf,
            content,
            max_bytes=MAX_DOCUMENT_BYTES,
            max_parts=MAX_DOCUMENT_SEGMENTS,
        )
    except document_extraction.DocumentExtractionError as exc:
        raise AIDocumentError(f"Could not process this large PDF: {exc}") from exc
    if not blobs:
        raise AIDocumentError("The document did not contain any readable pages.")
    return [[_document_part(blob, mime_type)] for blob in blobs]


async def extract_pdf_text_with_ai(content: bytes) -> str:
    """Transcribe an image-only PDF with the configured multimodal model."""
    if not content:
        return ""
    if len(content) <= MAX_DOCUMENT_BYTES:
        segments = [[_document_part(content, "application/pdf")]]
    else:
        segments = await _split_large_pdf(content, "application/pdf")

    prompt = {
        "text": (
            "Extract all readable text from this PDF in natural reading order. "
            "Preserve headings, paragraphs, table rows, dates, amounts, and clause "
            "labels. Return only the transcription, without commentary or Markdown "
            "code fences. Do not infer text that is not visible."
        )
    }
    semaphore = asyncio.Semaphore(MAX_SEGMENT_CONCURRENCY)

    async def _transcribe(segment: list[dict[str, Any]]) -> str:
        async with semaphore:
            return await _generate([prompt, *segment], temperature=0.0)

    outcomes = await asyncio.gather(
        *(_transcribe(segment) for segment in segments), return_exceptions=True
    )
    transcriptions: list[str] = []
    first_error: BaseException | None = None
    for outcome in outcomes:
        if isinstance(outcome, BaseException):
            first_error = first_error or outcome
            logger.warning("AI PDF transcription segment failed: %s", outcome)
        elif outcome.strip():
            transcriptions.append(outcome.strip())
    if not transcriptions and first_error:
        raise first_error
    return "\n\n".join(transcriptions)[:MAX_AI_EXTRACTED_CHARS].strip()


def _segment_label(document_label: str, index: int, total: int) -> str:
    if total <= 1:
        return f"\n\n{document_label}:\n"
    return (
        f"\n\nThis is PART {index + 1} OF {total} of a single large document. "
        "Base your answer only on what appears in this part; leave anything not "
        f"present here unset.\n{document_label} (part {index + 1} of {total}):\n"
    )


async def _document_segments(
    content: bytes,
    mime_type: str,
    text_content: str | None,
    *,
    document_label: str,
) -> list[list[dict[str, Any]]]:
    """Build the ordered document parts for each model call.

    Returns one list of Gemini content parts per segment: a single segment for
    ordinary documents, several for large ones (see the module-level
    *Large-document strategy* notes). Returns an empty list when there is no
    document at all (callers that treat the document as optional).
    """
    if text_content is not None:
        chunks = _split_text(text_content)
        if not chunks:
            raise AIRequestError("The document did not contain any readable text.")
    elif content:
        is_pdf = "pdf" in (mime_type or "").lower()
        if is_pdf:
            # Compressed byte size is not a reliable measure of document length:
            # a text-heavy, multi-hundred-page PDF can still fit below the inline
            # byte ceiling. Prefer its text layer whenever usable so it can be
            # segmented instead of asking the model to digest the entire PDF in
            # one request.
            extracted = await _extract_pdf_text(content)
            if len(extracted.strip()) >= MIN_USABLE_PDF_TEXT_CHARS:
                chunks = _split_text(extracted)
                if chunks:
                    total = len(chunks)
                    return [
                        [{"text": _segment_label(document_label, i, total) + chunk}]
                        for i, chunk in enumerate(chunks)
                    ]
            transcribed = await extract_pdf_text_with_ai(content)
            chunks = _split_text(transcribed)
            if not chunks:
                raise AIDocumentError(
                    "The AI assistant could not find readable text in this PDF."
                )
            total = len(chunks)
            return [
                [{"text": _segment_label(document_label, i, total) + chunk}]
                for i, chunk in enumerate(chunks)
            ]
        if len(content) <= MAX_DOCUMENT_BYTES:
            return [[_document_part(content, mime_type)]]
        raise AIDocumentError(
            f"This file is too large for AI processing "
            f"(over {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB of image data). "
            "Convert it to a PDF or a text document, or split it into "
            "smaller files."
        )
    else:
        return []

    total = len(chunks)
    return [
        [{"text": _segment_label(document_label, i, total) + chunk}]
        for i, chunk in enumerate(chunks)
    ]


async def _generate_over_segments(
    prompt_parts: list[dict[str, Any]],
    segments: list[list[dict[str, Any]]],
    *,
    system_instruction: str | None = None,
    temperature: float = 0.2,
) -> list[str]:
    """Run the same prompt against every document segment, in order.

    Segments run with bounded concurrency to keep large-document latency
    reasonable without stampeding the provider. A segment that fails is skipped
    so one bad chunk cannot discard the rest of the document; if *every* segment
    fails the underlying error is raised.
    """
    if len(segments) <= 1:
        parts = prompt_parts + (segments[0] if segments else [])
        return [
            await _generate(
                parts,
                system_instruction=system_instruction,
                json_response=True,
                temperature=temperature,
            )
        ]

    semaphore = asyncio.Semaphore(MAX_SEGMENT_CONCURRENCY)

    async def _run(segment: list[dict[str, Any]]) -> str:
        async with semaphore:
            return await _generate(
                prompt_parts + segment,
                system_instruction=system_instruction,
                json_response=True,
                temperature=temperature,
            )

    outcomes = await asyncio.gather(
        *(_run(segment) for segment in segments), return_exceptions=True
    )
    texts: list[str] = []
    first_error: BaseException | None = None
    for outcome in outcomes:
        if isinstance(outcome, BaseException):
            first_error = first_error or outcome
            logger.warning("AI segment failed: %s", outcome)
        else:
            texts.append(outcome)
    if not texts:
        raise first_error if first_error else AIRequestError(
            "AI provider returned no usable response"
        )
    return texts


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


# Keys (in priority order) that identify the same record across segments when
# merging list-shaped results such as a year-by-year rent/CAM schedule.
_LIST_ITEM_KEYS = ("year", "period", "period_start", "category", "name", "id")


def _list_item_key(item: Any) -> str:
    """A stable identity for a list element, used to dedupe across segments."""
    if isinstance(item, dict):
        for key in _LIST_ITEM_KEYS:
            value = item.get(key)
            if not _is_empty(value):
                return f"{key}={str(value).strip().lower()}"
        return json.dumps(item, sort_keys=True, default=str)
    return json.dumps(item, sort_keys=True, default=str)


def _merge_segment_lists(current: list[Any], value: list[Any]) -> list[Any]:
    """Concatenate two per-segment lists, deduping and merging by item identity.

    A rent or CAM schedule split across the segments of a large document arrives
    as a list per segment; concatenating them (rather than letting the first
    segment win) is what keeps the later years. Elements identifying the same
    record — the same ``year``, say — are merged field-by-field with the same
    earlier-wins rule used for objects.
    """
    merged: list[Any] = []
    index: dict[str, int] = {}
    for item in [*current, *value]:
        if _is_empty(item):
            continue
        key = _list_item_key(item)
        position = index.get(key)
        if position is None:
            index[key] = len(merged)
            merged.append(item)
        elif isinstance(merged[position], dict) and isinstance(item, dict):
            merged[position] = _merge_segment_results([merged[position], item])
    return merged


def _merge_segment_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge per-segment JSON objects into one, earlier segments winning.

    Keys populated by an earlier segment are kept (documents state their key
    terms up front); keys still empty are filled from later segments, so values
    that only appear deep in a large document are not lost. Nested objects are
    merged recursively with the same rule, and lists are unioned by item
    identity so multi-row results (e.g. a rent schedule) survive segmentation.
    """
    merged: dict[str, Any] = {}
    for result in results:
        if not isinstance(result, dict):
            continue
        for key, value in result.items():
            if _is_empty(value):
                merged.setdefault(key, value)
                continue
            current = merged.get(key)
            if isinstance(current, dict) and isinstance(value, dict):
                merged[key] = _merge_segment_results([current, value])
            elif isinstance(current, list) and isinstance(value, list):
                merged[key] = _merge_segment_lists(current, value)
            elif key not in merged or _is_empty(current):
                merged[key] = value
    return merged


async def _generate_json_over_segments(
    prompt_parts: list[dict[str, Any]],
    segments: list[list[dict[str, Any]]],
    *,
    system_instruction: str | None = None,
) -> dict[str, Any]:
    """Run a JSON prompt across every segment and merge the parsed objects."""
    texts = await _generate_over_segments(
        prompt_parts, segments, system_instruction=system_instruction
    )
    if len(texts) == 1:
        return _parse_json_object(texts[0])
    parsed: list[dict[str, Any]] = []
    for text in texts:
        try:
            parsed.append(_parse_json_object(text))
        except AIRequestError as exc:  # tolerate one malformed segment
            logger.warning("Discarding unparseable AI segment: %s", exc)
    if not parsed:
        raise AIRequestError("AI provider did not return valid JSON")
    return _merge_segment_results(parsed)


# ── Public helpers ────────────────────────────────────────────────────────────

LEASE_PARSE_SYSTEM = (
    "You are a commercial real-estate lease abstraction assistant. Extract key "
    "lease details from the supplied document. Respond ONLY with a JSON object. "
    "Use null for any field you cannot determine. Dates must be ISO 8601 "
    "(YYYY-MM-DD). Do not invent values.\n"
    "\n"
    "Financial extraction rules:\n"
    "- Return all monetary amounts as plain numbers (no currency symbols, commas, "
    "or thousands separators), e.g. 12500.50 not \"$12,500.50\".\n"
    "- payment_amount must be the base rent for ONE payment_frequency period. If "
    "the lease states an annual base rent but rent is paid monthly, divide by 12 "
    "and set payment_frequency to monthly. If it states a per-square-foot rate, "
    "multiply by the rentable area to get the periodic amount when the area is "
    "given.\n"
    "- Express rates (annual_escalation_rate, incremental_borrowing_rate) as "
    "decimal fractions, e.g. 3% becomes 0.03 and 4.5% becomes 0.045.\n"
    "- Prefer the most recent/initial base rent at commencement when a rent "
    "schedule lists multiple steps."
)

# The fields we ask Gemini to populate map directly onto LeaseCreate (including
# the ASC 842 / IFRS 16 accounting & financial terms).
LEASE_PARSE_FIELDS = {
    "lease_name": "Short human name for the lease, e.g. tenant or suite",
    "lessor_name": "The landlord / lessor legal name",
    "lease_commencement_date": "Commencement date (YYYY-MM-DD)",
    "lease_expiration": "Expiration / termination date (YYYY-MM-DD)",
    "lease_notice_date": "Date by which renewal/termination notice must be given (YYYY-MM-DD)",
    "notice_period": "Notice period as written, e.g. '90 days'",
    "notice_period_days": "Notice period in whole days (integer)",
    "expiration_year": "Year the lease expires (integer)",
    # ── Accounting & financial terms (ASC 842 / IFRS 16) ──────────────────────
    "payment_amount": "Base rent for a SINGLE payment period as a plain number (no symbols/commas), matching payment_frequency",
    "payment_frequency": "Billing cadence of the base rent: one of monthly, quarterly, annually",
    "annual_escalation_rate": "Annual rent escalation as a decimal fraction, e.g. 0.03 for 3%",
    "accounting_standard": "Accounting standard if stated: one of asc842, ifrs16, both",
    "lease_classification": "Lease classification if determinable: operating or finance",
    "incremental_borrowing_rate": "Incremental borrowing / discount rate as a decimal fraction, e.g. 0.045 for 4.5%",
    "initial_direct_costs": "Initial direct costs capitalised at commencement as a plain number",
    "lease_incentives": "Lease incentives / tenant improvement allowances received from the lessor as a plain number",
    "prepaid_rent": "Prepaid rent paid at or before commencement as a plain number",
    "residual_value_guarantee": "Residual value guaranteed by the lessee as a plain number",
    "is_short_term_lease": "True if the total lease term is 12 months or less (boolean)",
    "is_low_value_lease": "True if the underlying asset is low-value (boolean)",
    "currency": "ISO 4217 currency code of the payments, e.g. USD",
}


async def _parse_fields_from_document(
    *,
    parser: str,
    system_instruction: str,
    field_spec_map: dict[str, str],
    intro: str,
    document_label: str,
    content: bytes,
    mime_type: str,
    text_content: str | None = None,
) -> dict[str, Any]:
    """Extract a fixed set of structured fields from a document.

    Shared engine behind the per-entity ``parse_*`` helpers. For PDFs and images
    the raw bytes are sent inline (Gemini reads them natively); for formats
    Gemini cannot parse directly (e.g. Word documents) the caller extracts plain
    text first and passes it as ``text_content``. Documents too large for a
    single call are segmented and the per-segment field sets merged, so a value
    that only appears late in the document is still populated.

    Identical (parser, prompt version, model, document) calls are served from a
    small in-process cache to cut latency and provider spend.
    """
    payload = _cache_payload(content, text_content)
    key = _cache_key(parser, payload)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    field_spec = "\n".join(f"- {k}: {v}" for k, v in field_spec_map.items())
    prompt = f"{intro}\n{field_spec}\n"
    segments = await _document_segments(
        content, mime_type, text_content, document_label=document_label
    )
    result = await _generate_json_over_segments(
        [{"text": prompt}], segments, system_instruction=system_instruction
    )
    _cache_put(key, result)
    return result


async def parse_lease_document(
    content: bytes,
    mime_type: str,
    *,
    text_content: str | None = None,
) -> dict[str, Any]:
    """Extract structured lease fields from a document.

    For PDFs and images the raw bytes are sent inline (Gemini reads them
    natively). For formats Gemini cannot parse directly (e.g. Word documents),
    the caller extracts plain text first and passes it as ``text_content``; that
    text is then sent in place of the inline document.

    Returns a dict whose keys are a subset of :class:`LeaseCreate` fields.
    """
    return await _parse_fields_from_document(
        parser="lease",
        system_instruction=LEASE_PARSE_SYSTEM,
        field_spec_map=LEASE_PARSE_FIELDS,
        intro=(
            "Extract the following fields from the lease document and "
            "return a single JSON object with exactly these keys:"
        ),
        document_label="LEASE DOCUMENT TEXT",
        content=content,
        mime_type=mime_type,
        text_content=text_content,
    )


# ── Historical lease financials (per-year rent / CAM schedule) ───────────────

LEASE_HISTORY_SYSTEM = (
    "You are a commercial real-estate lease abstraction assistant. The supplied "
    "document may be a current lease, an expired/prior lease, an amendment, a "
    "rent or CAM schedule, or a year-end operating-expense reconciliation "
    "statement. Extract the YEAR-BY-YEAR financial history it states.\n"
    "\n"
    "Respond ONLY with a JSON object of the form "
    '{"period_start": "YYYY-MM-DD"|null, "period_end": "YYYY-MM-DD"|null, '
    '"periods": [{...}]}. One element of \'periods\' per lease year the '
    "document states figures for.\n"
    "\n"
    "Each period object uses exactly these keys:\n"
    "- year: the calendar or lease year as an integer, e.g. 2019\n"
    "- period_start / period_end: the period's bounds (YYYY-MM-DD) when the "
    "year is partial or does not follow the calendar; null otherwise\n"
    "- base_rent_amount: base rent for ONE base_rent_frequency period\n"
    "- base_rent_frequency: monthly, quarterly or annually\n"
    "- base_rent_escalation_rate: that year's rent escalation as a decimal "
    "fraction\n"
    "- amount: the year's total CAM / common-area-maintenance charge\n"
    "- percent_increase: the year's CAM increase over the prior year as a "
    "decimal fraction, when CAM is quoted as an increase rather than an amount\n"
    "- cam_psf: CAM expressed per rentable square foot, when stated\n"
    "- operating_expense_amount: the year's operating-expense / opex total\n"
    "- reconciliation_true_up: the year-end reconciliation settlement; positive "
    "when the tenant owed a true-up, negative for a credit to the tenant\n"
    "- notes: a short note on what the figures came from\n"
    "- confidence: your confidence in this row from 0 to 1\n"
    "\n"
    "Rules:\n"
    "- Return all monetary amounts as plain numbers (no currency symbols, "
    'commas, or thousands separators), e.g. 12500.50 not "$12,500.50".\n'
    "- Express every percentage as a decimal fraction: 3% becomes 0.03.\n"
    "- Never mix cadences: if a figure is annual, set base_rent_frequency to "
    "annually rather than dividing it yourself.\n"
    "- Use null for anything the document does not state. Do NOT invent, "
    "interpolate or extrapolate values for years the document is silent on.\n"
    "- Return an empty 'periods' list when the document states no year-by-year "
    "figures at all."
)


async def parse_lease_financial_history(
    content: bytes,
    mime_type: str,
    *,
    text_content: str | None = None,
) -> dict[str, Any]:
    """Extract a document's year-by-year lease financials.

    Used to onboard an existing tenancy: prior leases, amendments and
    reconciliation statements are read into per-year rows that a human reviews
    before they are saved onto the lease's CAM schedule as *historical*
    reference data. Nothing here writes to the database, and the values are
    never applied to the active lease's own financial terms.

    Returns ``{"period_start", "period_end", "periods": [...]}``. Large
    documents are segmented and the per-segment ``periods`` lists merged by
    year, so a rent schedule spanning many pages is not truncated to whatever
    the first segment happened to contain.
    """
    payload = _cache_payload(content, text_content)
    key = _cache_key("lease_history", payload)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    prompt = (
        "Extract the year-by-year financial history stated by this document and "
        "return a single JSON object with the keys 'period_start', 'period_end' "
        "and 'periods'.\n"
    )
    segments = await _document_segments(
        content, mime_type, text_content, document_label="LEASE DOCUMENT TEXT"
    )
    result = await _generate_json_over_segments(
        [{"text": prompt}], segments, system_instruction=LEASE_HISTORY_SYSTEM
    )
    periods = result.get("periods")
    normalized = {
        "period_start": result.get("period_start"),
        "period_end": result.get("period_end"),
        "periods": periods if isinstance(periods, list) else [],
    }
    _cache_put(key, normalized)
    return normalized


# ── Vendor bill / AP invoice extraction (maps onto BillCreate) ────────────────

VENDOR_BILL_PARSE_SYSTEM = (
    "You are an accounts-payable assistant. Extract the header details of a "
    "vendor invoice / bill from the supplied document. Respond ONLY with a JSON "
    "object. Use null for any field you cannot determine. Dates must be ISO 8601 "
    "(YYYY-MM-DD). Do not invent values.\n"
    "\n"
    "- Return all monetary amounts as plain numbers (no currency symbols, "
    "commas, or thousands separators), e.g. 12500.50 not \"$12,500.50\".\n"
    "- total_amount is the invoice grand total (amount due).\n"
    "- vendor_name is the company that issued the invoice (the payee), not the "
    "bill-to / customer."
)

VENDOR_BILL_PARSE_FIELDS = {
    "vendor_name": "Name of the vendor / supplier that issued the invoice",
    "bill_number": "Invoice or bill number / reference as printed",
    "bill_date": "Invoice date (YYYY-MM-DD)",
    "due_date": "Payment due date if stated (YYYY-MM-DD)",
    "total_amount": "Invoice grand total / amount due as a plain number",
    "currency": "ISO 4217 currency code of the amounts, e.g. USD",
    "memo": "Short description of what the invoice is for",
}


async def parse_vendor_bill_document(
    content: bytes,
    mime_type: str,
    *,
    text_content: str | None = None,
) -> dict[str, Any]:
    """Extract suggested vendor-bill header fields from an invoice document."""
    return await _parse_fields_from_document(
        parser="vendor_bill",
        system_instruction=VENDOR_BILL_PARSE_SYSTEM,
        field_spec_map=VENDOR_BILL_PARSE_FIELDS,
        intro=(
            "Extract the following fields from the vendor invoice / bill and "
            "return a single JSON object with exactly these keys:"
        ),
        document_label="VENDOR INVOICE TEXT",
        content=content,
        mime_type=mime_type,
        text_content=text_content,
    )


# ── Insurance certificate (COI) extraction (maps onto CertCreate) ─────────────

INSURANCE_PARSE_SYSTEM = (
    "You are an insurance compliance assistant. Extract the key details from a "
    "Certificate of Insurance (ACORD or similar). Respond ONLY with a JSON "
    "object. Use null for any field you cannot determine. Dates must be ISO 8601 "
    "(YYYY-MM-DD). Do not invent values.\n"
    "\n"
    "- insurer is the insurance carrier / underwriting company.\n"
    "- certificate_holder is the entity the certificate is issued to (the holder "
    "box), not the insured.\n"
    "- limits should be a short human-readable summary of the coverage limits, "
    "e.g. 'GL $1M/$2M; Auto $1M; Umbrella $5M'."
)

INSURANCE_PARSE_FIELDS = {
    "certificate_type": "Type of coverage, e.g. 'General Liability', 'Workers Comp', 'Auto', 'Umbrella'",
    "insurer": "Insurance carrier / underwriting company name",
    "policy_number": "Policy number as printed",
    "effective_date": "Policy effective date (YYYY-MM-DD)",
    "expiration_date": "Policy expiration date (YYYY-MM-DD)",
    "limits": "Short human-readable summary of coverage limits",
    "certificate_holder": "Entity the certificate is issued to (the certificate holder)",
    "notes": "Any other relevant notes, e.g. additional insured / waiver of subrogation",
}


async def parse_insurance_certificate(
    content: bytes,
    mime_type: str,
    *,
    text_content: str | None = None,
) -> dict[str, Any]:
    """Extract suggested certificate-of-insurance fields from a document."""
    return await _parse_fields_from_document(
        parser="insurance",
        system_instruction=INSURANCE_PARSE_SYSTEM,
        field_spec_map=INSURANCE_PARSE_FIELDS,
        intro=(
            "Extract the following fields from the certificate of insurance and "
            "return a single JSON object with exactly these keys:"
        ),
        document_label="CERTIFICATE OF INSURANCE TEXT",
        content=content,
        mime_type=mime_type,
        text_content=text_content,
    )


# ── HVAC contract extraction (maps onto HvacContractCreate) ───────────────────

HVAC_CONTRACT_PARSE_SYSTEM = (
    "You are a facilities-management assistant. Extract the key details from an "
    "HVAC service / maintenance contract or agreement. Respond ONLY with a JSON "
    "object. Use null for any field you cannot determine. Dates must be ISO 8601 "
    "(YYYY-MM-DD). Do not invent values.\n"
    "\n"
    "- hvac_company is the contractor / service provider performing the work.\n"
    "- frequency is the service cadence if stated, e.g. 'Monthly', 'Quarterly', "
    "'Bi-Annual', 'Annual', 'On-Demand'.\n"
    "- landlord_handles is true only if the document indicates the landlord (not "
    "the tenant) is responsible for HVAC maintenance."
)

HVAC_CONTRACT_PARSE_FIELDS = {
    "hvac_company": "Name of the HVAC contractor / service provider",
    "contact": "Primary contact name, phone, or email for the contractor",
    "frequency": "Service cadence, e.g. Monthly, Quarterly, Bi-Annual, Annual, On-Demand",
    "next_service_date": "Next scheduled service date if stated (YYYY-MM-DD)",
    "last_serviced_date": "Most recent service date if stated (YYYY-MM-DD)",
    "office_name": "Office / site name or location covered by the contract",
    "landlord_handles": "true if the landlord is responsible for HVAC maintenance (boolean)",
    "comments": "Any other relevant notes about scope, term, or pricing",
}


async def parse_hvac_contract(
    content: bytes,
    mime_type: str,
    *,
    text_content: str | None = None,
) -> dict[str, Any]:
    """Extract suggested HVAC-contract fields from a document."""
    return await _parse_fields_from_document(
        parser="hvac_contract",
        system_instruction=HVAC_CONTRACT_PARSE_SYSTEM,
        field_spec_map=HVAC_CONTRACT_PARSE_FIELDS,
        intro=(
            "Extract the following fields from the HVAC service contract and "
            "return a single JSON object with exactly these keys:"
        ),
        document_label="HVAC CONTRACT TEXT",
        content=content,
        mime_type=mime_type,
        text_content=text_content,
    )


# ── Lease template drafting from a document (Residential parity) ──────────────
#
# Unlike the field parsers above, this turns a real lease document into a
# reusable :class:`~app.models.lease_template.LeaseTemplate` body: the model
# rewrites the concrete lease into a generic template, replacing tenant/unit/term
# specifics with ``{{merge_field}}`` placeholders so staff can reuse it to send
# and e-sign future resident leases.

# Merge fields the resident-lease e-signing engine can interpolate. Keep this in
# sync with the merge context exposed by the leasing / waiver e-sign engine.
LEASE_TEMPLATE_MERGE_FIELDS = {
    "landlord_name": "The organisation / lessor legal name",
    "tenant_name": "The resident / tenant full name",
    "unit_number": "The rental unit number or identifier",
    "property_address": "The full street address of the property/unit",
    "lease_start_date": "Lease commencement date",
    "lease_end_date": "Lease expiration date",
    "lease_term": "The lease term, e.g. '12 months'",
    "monthly_rent": "The monthly rent amount",
    "security_deposit": "The security deposit amount",
    "rent_due_day": "Day of the month rent is due",
    "late_fee": "Late fee amount or terms",
    "signing_date": "Date the lease is signed",
}

LEASE_TEMPLATE_SYSTEM = (
    "You are a residential leasing assistant that converts a concrete lease "
    "document into a REUSABLE lease template. Rewrite the supplied lease so that "
    "any detail specific to one tenant, unit, or term is replaced with a "
    "{{merge_field}} placeholder, while preserving the legal clauses, structure, "
    "headings, and wording of the original. Respond ONLY with a JSON object.\n"
    "\n"
    "Rules:\n"
    "- Only use placeholders from the provided merge-field list; use the EXACT "
    "double-brace syntax, e.g. {{tenant_name}}. Do not invent new placeholders.\n"
    "- Replace concrete values (names, addresses, unit numbers, dates, dollar "
    "amounts, term lengths) with the matching placeholder. Leave standard legal "
    "clause text intact.\n"
    "- Preserve the document's paragraph/section structure and readable "
    "formatting (line breaks, numbered clauses).\n"
    "- Do NOT invent clauses, obligations, or terms that are not in the source "
    "document.\n"
    "- The JSON object must have exactly these keys: name (a short descriptive "
    "template name), description (one sentence describing the template), and body "
    "(the full templated lease text with placeholders)."
)


async def draft_lease_template_from_document(
    content: bytes,
    mime_type: str,
    *,
    text_content: str | None = None,
) -> dict[str, Any]:
    """Turn a lease document into a reusable lease-template ``{name, description, body}``.

    For PDFs/images the raw bytes are sent inline; for Word/text documents the
    caller extracts plain text first and passes it as ``text_content``. A lease
    too large for one call is templated segment by segment and the bodies are
    concatenated in document order.
    """
    payload = _cache_payload(content, text_content)
    key = _cache_key("lease_template", payload)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    merge_spec = "\n".join(
        f"- {{{{{k}}}}}: {v}" for k, v in LEASE_TEMPLATE_MERGE_FIELDS.items()
    )
    prompt = (
        "Convert the following lease document into a reusable lease template. "
        "Use only these merge fields where a tenant/unit/term-specific value "
        "appears:\n" + merge_spec + "\n"
    )
    segments = await _document_segments(
        content, mime_type, text_content, document_label="LEASE DOCUMENT TEXT"
    )
    texts = await _generate_over_segments(
        [{"text": prompt}], segments, system_instruction=LEASE_TEMPLATE_SYSTEM
    )
    name = ""
    description = None
    bodies: list[str] = []
    for text in texts:
        try:
            result = _parse_json_object(text)
        except AIRequestError as exc:  # tolerate one malformed segment
            logger.warning("Discarding unparseable lease-template segment: %s", exc)
            continue
        body = result.get("body")
        if not isinstance(body, str) or not body.strip():
            continue
        bodies.append(body.strip())
        if not name:
            name = str(result.get("name") or "").strip()
            description = result.get("description") or None
    if not bodies:
        raise AIRequestError("AI provider did not return a template body")
    normalized = {
        "name": (name or "Lease Template")[:255],
        "description": description,
        "body": "\n\n".join(bodies),
    }
    _cache_put(key, normalized)
    return normalized
#
# Unlike the document parsers above, ticket triage and email drafting work from
# short free-text inputs rather than uploaded files, so they don't go through
# ``_parse_fields_from_document``. They still reuse ``_generate`` /
# ``_parse_json_object`` and the in-process cache (keyed on the JSON-serialised
# input) to cut latency and provider spend on identical repeat calls.

TICKET_TRIAGE_SYSTEM = (
    "You are a commercial-property facilities dispatcher. Given a maintenance "
    "request, classify it so a property manager can triage it quickly. Respond "
    "ONLY with a JSON object. Use null when you cannot determine a value. Never "
    "invent a category or vendor that is not in the provided lists.\n"
    "\n"
    "- category MUST be EXACTLY one of the provided category names, or null.\n"
    "- priority MUST be one of: low, medium, high. Use high for safety hazards, "
    "security issues, loss of heat/AC, water leaks, power loss, or anything "
    "blocking business operations; low for cosmetic or non-urgent issues; medium "
    "otherwise.\n"
    "- vendor MUST be EXACTLY one of the provided vendor names whose services "
    "best match the work, or null if none clearly fit.\n"
    "- reasoning is ONE short sentence explaining the suggestion."
)


async def triage_ticket(
    subject: str,
    description: str,
    *,
    categories: list[str],
    vendors: list[dict[str, Any]],
) -> dict[str, Any]:
    """Suggest a category, priority, and vendor for a maintenance request.

    ``categories`` is the list of the org's category names. ``vendors`` is a
    list of ``{"name": ..., "services": ...}`` dicts. The model is constrained to
    pick only from those lists (mirroring the abstract-catalog approach); the
    caller maps the returned names back onto ids. Returns a dict with keys
    ``category``, ``priority``, ``vendor``, and ``reasoning``.
    """
    cache_input = json.dumps(
        {
            "subject": subject,
            "description": description,
            "categories": sorted(categories),
            "vendors": sorted(
                (v.get("name", ""), v.get("services") or "") for v in vendors
            ),
        },
        sort_keys=True,
    ).encode("utf-8", "ignore")
    key = _cache_key("ticket_triage", cache_input)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    cat_list = "\n".join(f"- {c}" for c in categories) or "(none defined)"
    ven_list = (
        "\n".join(
            f"- {v.get('name', '')}: {v.get('services') or 'general maintenance'}"
            for v in vendors
        )
        or "(none available)"
    )
    prompt = (
        "Maintenance request to triage:\n"
        f"Subject: {subject}\n"
        f"Description: {description}\n"
        "\n"
        "Available categories:\n"
        f"{cat_list}\n"
        "\n"
        "Available vendors (name: services):\n"
        f"{ven_list}\n"
        "\n"
        "Return a single JSON object with exactly these keys: category, "
        "priority, vendor, reasoning."
    )
    text = await _generate(
        [{"text": prompt}], system_instruction=TICKET_TRIAGE_SYSTEM, json_response=True
    )
    result = _parse_json_object(text)
    _cache_put(key, result)
    return result


TICKET_EMAIL_DRAFT_SYSTEM = (
    "You are a facilities intake assistant. Convert a free-text maintenance "
    "request email into a structured ticket draft for human review. Respond ONLY "
    "with a JSON object. Use null for any field you cannot determine. Never "
    "invent details that are not in the email.\n"
    "\n"
    "- subject is a short (max ~80 chars) summary of the problem.\n"
    "- description is a clear, concise restatement of the reported issue.\n"
    "- priority MUST be one of: low, medium, high (high for safety/operational "
    "emergencies, low for cosmetic/non-urgent, medium otherwise).\n"
    "- category MUST be EXACTLY one of the provided category names, or null.\n"
    "- location_hint is any building/suite/site reference mentioned, or null."
)

TICKET_EMAIL_DRAFT_FIELDS = {
    "subject": "Short summary of the problem (max ~80 characters)",
    "description": "Clear, concise restatement of the reported issue",
    "priority": "One of: low, medium, high",
    "category": "EXACTLY one of the provided category names, or null",
    "location_hint": "Any building / suite / site reference mentioned, or null",
}


async def draft_ticket_from_email(
    email_text: str,
    *,
    categories: list[str],
) -> dict[str, Any]:
    """Draft structured ticket fields from a free-text request email.

    Returns a dict with keys ``subject``, ``description``, ``priority``,
    ``category``, and ``location_hint`` for the form to apply after review.
    """
    body = (email_text or "").strip()
    if not body:
        raise AIRequestError("The email did not contain any readable text.")
    body = body[:MAX_TEXT_CHARS]

    cache_input = json.dumps(
        {"email": body, "categories": sorted(categories)}, sort_keys=True
    ).encode("utf-8", "ignore")
    key = _cache_key("ticket_email_draft", cache_input)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    field_spec = "\n".join(f"- {k}: {v}" for k, v in TICKET_EMAIL_DRAFT_FIELDS.items())
    cat_list = "\n".join(f"- {c}" for c in categories) or "(none defined)"
    prompt = (
        "Convert the following maintenance request email into a single JSON "
        "object with exactly these keys:\n"
        f"{field_spec}\n"
        "\n"
        "Available categories:\n"
        f"{cat_list}\n"
        "\n"
        "REQUEST EMAIL TEXT:\n"
        f"{body}"
    )
    text = await _generate(
        [{"text": prompt}],
        system_instruction=TICKET_EMAIL_DRAFT_SYSTEM,
        json_response=True,
    )
    result = _parse_json_object(text)
    _cache_put(key, result)
    return result


ABSTRACT_SUGGEST_SYSTEM = (
    "You are a commercial lease abstraction assistant. For each requested clause "
    "category, extract the relevant lease provisions into the category's "
    "structured fields, and also summarise them concisely and factually. "
    "Respond ONLY with a JSON object keyed by category_key; each value is an "
    "object whose keys are the field keys listed for that category. Populate "
    "every field you can from the document, putting discrete values in their "
    "dedicated fields (e.g. a 60-day notice period belongs in the notice-days "
    "field, not only the summary). Match each field's type: 'number'/'currency'/"
    "'percent' as JSON numbers (digits only, no units or symbols), 'boolean' as "
    "true/false, 'date' as 'YYYY-MM-DD', 'select' as one of the provided options, "
    "and 'text'/'textarea' as strings. Always include a 'summary' field "
    "summarising the category and a 'notes' field for any extra narrative. Omit "
    "fields the document does not address (or use an empty string). Never invent "
    "terms or values that are not in the document."
)


def _format_category_fields(category: dict[str, Any]) -> str:
    """Render a category's field schema as a prompt bullet list."""
    lines: list[str] = []
    for field in category.get("fields", []):
        ftype = field.get("type", "text")
        descriptor = f"    - {field['key']} ({ftype}): {field['label']}"
        options = field.get("options")
        if options:
            descriptor += f" [one of: {', '.join(options)}]"
        lines.append(descriptor)
    return "\n".join(lines)


async def suggest_abstract_clauses(
    content: bytes,
    mime_type: str,
    categories: list[dict[str, Any]],
    *,
    text_content: str | None = None,
) -> dict[str, Any]:
    """Propose lease-abstract clause content per category.

    ``categories`` is a list of ``{"key": ..., "name": ..., "fields": [...]}``
    dicts taken from the lease-abstract catalog, where each field is a
    ``{"key", "label", "type", "options"?}`` schema. Returns a dict keyed by
    category key whose values map field keys to extracted values.

    For PDFs and images the raw bytes are sent inline (Gemini reads them
    natively). For formats Gemini cannot parse directly (e.g. Word/text
    documents), the caller extracts plain text first and passes it as
    ``text_content``; that text is sent in place of the inline document.
    """
    cat_blocks: list[str] = []
    for c in categories:
        block = f"- {c['key']}: {c['name']}"
        fields = _format_category_fields(c)
        if fields:
            block += "\n  fields:\n" + fields
        cat_blocks.append(block)
    cat_spec = "\n".join(cat_blocks)
    prompt = (
        "Abstract the lease into structured fields for each of these clause "
        "categories. Each category lists its field keys, types, and labels; "
        "return a JSON object per category keyed by those field keys:\n"
        f"{cat_spec}\n"
    )
    segments = await _document_segments(
        content, mime_type, text_content, document_label="LEASE DOCUMENT TEXT"
    )
    return await _generate_json_over_segments(
        [{"text": prompt}], segments, system_instruction=ABSTRACT_SUGGEST_SYSTEM
    )

# ── Lease abstract gap-detection (QA pass) ───────────────────────────────────

ABSTRACT_GAP_SYSTEM = (
    "You are a commercial real-estate lease abstraction QA reviewer. You are "
    "given a lease's clause-abstraction catalog, the content captured so far for "
    "each clause category, and (when available) the lease document text. Your job "
    "is to flag GAPS a reviewer should resolve before relying on the abstract:\n"
    "- missing: the lease appears not to address the category, or nothing was "
    "captured for it.\n"
    "- ambiguous: the captured content or the lease language is unclear, "
    "conflicting, or open to interpretation.\n"
    "- incomplete: a material term for the category was not captured (e.g. a "
    "renewal option with no exercise window or notice period).\n"
    "\n"
    "Respond ONLY with a JSON object of the form "
    '{"gaps": [{"category_key": "...", "gap_type": "missing|ambiguous|incomplete", '
    '"severity": "high|medium|low", "message": "...", "recommendation": "..."}]}.\n'
    "Rules:\n"
    "- category_key must be one of the supplied category keys.\n"
    "- Only include a category when there is a genuine gap; omit categories that "
    "are adequately captured.\n"
    "- Use high severity for legally or financially significant omissions (e.g. "
    "assignment/sublease, renewal options, security deposit, indemnification, "
    "expense recoveries), medium for material but lower-risk gaps, and low for "
    "minor or informational gaps.\n"
    "- message states the gap in one short sentence (e.g. 'No assignment clause "
    "found', 'Renewal option terms incomplete: no notice period captured').\n"
    "- recommendation states the concrete next step for the reviewer.\n"
    "- Do not invent lease terms. Base ambiguity/incompleteness on the supplied "
    "captured content and document text only."
)

_GAP_TYPES = ("missing", "ambiguous", "incomplete")
_GAP_SEVERITIES = ("high", "medium", "low")


def _format_captured_clause(category: dict[str, Any], captured: dict[str, Any] | None) -> str:
    """Render a category, its schema, and any captured content for the prompt."""
    lines = [f"- {category['key']}: {category['name']}"]
    fields = _format_category_fields(category)
    if fields:
        lines.append("  fields:\n" + fields)
    if captured:
        status = captured.get("status") or "needs_content"
        content = captured.get("content") or {}
        notes = (captured.get("notes") or "").strip()
        filled = {
            k: v for k, v in content.items() if v not in (None, "", [], {})
        }
        lines.append(f"  captured_status: {status}")
        if filled:
            lines.append(f"  captured_content: {json.dumps(filled, default=str)}")
        if notes:
            lines.append(f"  captured_notes: {notes[:1000]}")
        if not filled and not notes:
            lines.append("  captured_content: (nothing captured)")
    else:
        lines.append("  captured_content: (nothing captured)")
    return "\n".join(lines)


async def detect_abstract_gaps(
    categories: list[dict[str, Any]],
    captured: dict[str, dict[str, Any]],
    *,
    content: bytes = b"",
    mime_type: str = "",
    text_content: str | None = None,
) -> list[dict[str, Any]]:
    """Flag missing / ambiguous / incomplete clauses in a lease abstract.

    ``categories`` is the clause catalog (each ``{"key", "name", "fields"}``) and
    ``captured`` maps a category key to its stored ``{"status", "content",
    "notes"}``. When the lease document is supplied (inline ``content`` or
    extracted ``text_content``) the model also grounds gaps in the source text.

    Returns a list of ``{"category_key", "gap_type", "severity", "message",
    "recommendation"}`` findings for human review.
    """
    blocks = [_format_captured_clause(c, captured.get(c["key"])) for c in categories]
    prompt = (
        "Review this lease abstract for gaps. For each clause category below you "
        "are given its field schema and the content captured so far. Identify "
        "categories that are missing, ambiguous, or incomplete and return them as "
        "JSON gaps:\n"
        f"{chr(10).join(blocks)}\n"
    )
    parts: list[dict[str, Any]] = [{"text": prompt}]
    segments = await _document_segments(
        content, mime_type, text_content, document_label="LEASE DOCUMENT TEXT"
    )
    raws = await _generate_over_segments(
        parts, segments, system_instruction=ABSTRACT_GAP_SYSTEM
    )
    valid_keys = {c["key"] for c in categories}
    per_segment: list[list[dict[str, Any]]] = []
    for raw in raws:
        try:
            parsed = _parse_json_object(raw)
        except AIRequestError as exc:  # tolerate one malformed segment
            logger.warning("Discarding unparseable gap segment: %s", exc)
            continue
        per_segment.append(_normalize_gaps(parsed.get("gaps"), valid_keys))
    if not per_segment:
        raise AIRequestError("AI provider did not return valid JSON")
    return _merge_gap_findings(per_segment)


def _merge_gap_findings(per_segment: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Combine gap findings from each segment of a large document.

    Each segment only sees part of the lease, so a ``missing`` finding is only
    trustworthy when *every* segment reported it — otherwise the clause was
    simply in another part. ``ambiguous``/``incomplete`` findings are genuine
    local observations and are unioned, deduplicated by (category, gap type)
    keeping the highest severity.
    """
    if len(per_segment) == 1:
        return per_segment[0]

    severity_rank = {sev: i for i, sev in enumerate(_GAP_SEVERITIES)}
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    seen_missing: dict[str, int] = {}
    for findings in per_segment:
        for finding in findings:
            key = (finding["category_key"], finding["gap_type"])
            if finding["gap_type"] == "missing":
                seen_missing[finding["category_key"]] = (
                    seen_missing.get(finding["category_key"], 0) + 1
                )
            existing = merged.get(key)
            if existing is None or severity_rank.get(
                finding["severity"], 99
            ) < severity_rank.get(existing["severity"], 99):
                merged[key] = finding
    total = len(per_segment)
    return [
        finding
        for (category_key, gap_type), finding in merged.items()
        if gap_type != "missing" or seen_missing.get(category_key, 0) == total
    ]


def _normalize_gaps(gaps: Any, valid_keys: set[str]) -> list[dict[str, Any]]:
    """Coerce model output into a clean list of gap findings."""
    if not isinstance(gaps, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for item in gaps:
        if not isinstance(item, dict):
            continue
        key = str(item.get("category_key") or "").strip()
        if key not in valid_keys:
            continue
        gap_type = str(item.get("gap_type") or "").strip().lower()
        if gap_type not in _GAP_TYPES:
            gap_type = "incomplete"
        severity = str(item.get("severity") or "").strip().lower()
        if severity not in _GAP_SEVERITIES:
            severity = "medium"
        message = str(item.get("message") or "").strip()
        if not message:
            continue
        cleaned.append(
            {
                "category_key": key,
                "gap_type": gap_type,
                "severity": severity,
                "message": message[:500],
                "recommendation": str(item.get("recommendation") or "").strip()[:500],
            }
        )
    return cleaned


# ── CAM reconciliation anomaly review ────────────────────────────────────────

CAM_REVIEW_SYSTEM = (
    "You are a commercial real-estate CAM (common-area-maintenance) "
    "reconciliation auditor. You review a tenant's CAM reconciliation line items "
    "for a given year against (a) the prior year's reconciliation line items and "
    "(b) the lease's abstracted recovery clauses. Flag anomalies a human should "
    "investigate before finalizing the statement.\n"
    "\n"
    "Look for:\n"
    "- year_over_year: a line whose amount changed materially versus the prior "
    "year, or a category that newly appeared or disappeared. When "
    "'historical_periods' is supplied it holds the lease's imported prior-year "
    "financials (CAM, operating expenses, base rent, true-ups); use it as the "
    "multi-year trend baseline.\n"
    "- not_permitted: a charged category that is not within the expenses the "
    "lease permits the landlord to recover, or that the lease excludes.\n"
    "- cap_or_term: a charge that appears to conflict with a lease term such as a "
    "cap on increases, gross-up, base year, or expense stop.\n"
    "- other: any other clearly anomalous item.\n"
    "\n"
    "Respond ONLY with a JSON object of the form "
    '{"summary": "...", "anomalies": [{"category": "...", "anomaly_type": '
    '"year_over_year|not_permitted|cap_or_term|other", "severity": '
    '"high|medium|low", "message": "...", "recommendation": "..."}]}.\n'
    "Rules:\n"
    "- Only flag genuine anomalies; if everything looks consistent, return an "
    "empty anomalies list and a one-line summary.\n"
    "- Base 'not_permitted' findings strictly on the supplied lease clauses; if "
    "the lease does not clearly restrict recoverable categories, do not guess a "
    "violation.\n"
    "- message is one short sentence; recommendation is the concrete next step.\n"
    "- Do not invent figures; reason only from the supplied amounts and clauses."
)

_CAM_ANOMALY_TYPES = ("year_over_year", "not_permitted", "cap_or_term", "other")
_CAM_ANOMALY_SEVERITIES = ("high", "medium", "low")


async def review_cam_reconciliation(
    *,
    year: int,
    lines: list[dict[str, Any]],
    prior_year: int | None = None,
    prior_lines: list[dict[str, Any]] | None = None,
    lease_clauses: dict[str, Any] | None = None,
    historical_periods: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Flag anomalous CAM reconciliation line items for human review.

    ``lines`` (and ``prior_lines``) are line dicts with at least ``category`` and
    ``actual_amount``/``grossed_up_amount``. ``lease_clauses`` maps a clause label
    to the abstracted content that constrains recoveries (permitted categories,
    caps, gross-up, base year, etc). ``historical_periods`` carries the lease's
    imported prior-year financials (base rent, CAM, opex, true-up), which give
    the reviewer a multi-year baseline even when only one prior reconciliation
    statement exists in the system. Returns ``{"summary", "anomalies"}`` where
    each anomaly is ``{"category", "anomaly_type", "severity", "message",
    "recommendation"}``.
    """
    payload = {
        "year": year,
        "current_lines": lines,
        "prior_year": prior_year,
        "prior_lines": prior_lines or [],
        "lease_clauses": lease_clauses or {},
        "historical_periods": historical_periods or [],
    }
    blob = json.dumps(payload, default=str)
    if len(blob) > MAX_TEXT_CHARS:
        blob = blob[:MAX_TEXT_CHARS]
    prompt = (
        "Review this CAM reconciliation for anomalies and return a single JSON "
        "object with the keys 'summary' and 'anomalies'.\n"
        "Data (JSON):\n"
        f"{blob}\n"
    )
    raw = await _generate(
        [{"text": prompt}], system_instruction=CAM_REVIEW_SYSTEM, json_response=True
    )
    parsed = _parse_json_object(raw)
    return {
        "summary": str(parsed.get("summary") or "").strip()[:1000],
        "anomalies": _normalize_cam_anomalies(parsed.get("anomalies")),
    }


def _normalize_cam_anomalies(anomalies: Any) -> list[dict[str, Any]]:
    """Coerce model output into a clean list of CAM anomaly findings."""
    if not isinstance(anomalies, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for item in anomalies:
        if not isinstance(item, dict):
            continue
        message = str(item.get("message") or "").strip()
        if not message:
            continue
        anomaly_type = str(item.get("anomaly_type") or "").strip().lower()
        if anomaly_type not in _CAM_ANOMALY_TYPES:
            anomaly_type = "other"
        severity = str(item.get("severity") or "").strip().lower()
        if severity not in _CAM_ANOMALY_SEVERITIES:
            severity = "medium"
        cleaned.append(
            {
                "category": str(item.get("category") or "").strip()[:120],
                "anomaly_type": anomaly_type,
                "severity": severity,
                "message": message[:500],
                "recommendation": str(item.get("recommendation") or "").strip()[:500],
            }
        )
    return cleaned


# ── Inbound document classification & routing ────────────────────────────────

# The document types we can classify inbound items into. ``unknown`` is the
# catch-all when the model cannot confidently place a document.
INBOUND_DOCUMENT_TYPES = (
    "vendor_invoice",
    "insurance_certificate",
    "lease_amendment",
    "lease",
    "unknown",
)

_CLASSIFY_CONFIDENCES = ("high", "medium", "low")

# Per-type field schemas the model extracts to pre-fill the matching record.
# These map onto VendorBill, InsuranceCertificate, and Lease fields respectively.
INBOUND_CLASSIFY_FIELDS: dict[str, dict[str, str]] = {
    "vendor_invoice": {
        "vendor_name": "Name of the vendor / supplier that issued the invoice",
        "bill_number": "The vendor's invoice or bill number as printed",
        "bill_date": "Invoice/bill date (YYYY-MM-DD)",
        "due_date": "Payment due date (YYYY-MM-DD)",
        "total_amount": "Invoice total as a plain number (no symbols/commas)",
        "currency": "ISO 4217 currency code of the amount, e.g. USD",
        "memo": "Short description of what the invoice is for",
    },
    "insurance_certificate": {
        "insured_name": "The named insured the certificate covers (usually the vendor or landlord)",
        "certificate_type": "One of: general_liability, workers_comp, auto, umbrella, other",
        "insurer": "The insurance carrier / company providing coverage",
        "policy_number": "The policy number as printed",
        "effective_date": "Coverage effective date (YYYY-MM-DD)",
        "expiration_date": "Coverage expiration date (YYYY-MM-DD)",
        "limits": "Coverage limits as written, e.g. '$1,000,000 each occurrence'",
        "certificate_holder": "The certificate holder named on the COI",
    },
    "lease_amendment": {
        "lease_name": "Short name of the lease being amended (tenant/suite if present)",
        "lessor_name": "The landlord / lessor legal name on the amendment",
        "amendment_type": "Nature of the amendment: one of extension, rent_change, expansion, contraction, termination, other",
        "effective_date": "Date the amendment takes effect (YYYY-MM-DD)",
        "new_expiration_date": "New lease expiration date if the amendment changes it (YYYY-MM-DD)",
        "new_payment_amount": "New periodic base rent if the amendment changes it, as a plain number",
        "summary": "One or two sentence factual summary of what the amendment changes",
    },
    "lease": {
        "lease_name": "Short human name for the lease, e.g. tenant or suite",
        "lessor_name": "The landlord / lessor legal name",
        "lease_commencement_date": "Commencement date (YYYY-MM-DD)",
        "lease_expiration": "Expiration / termination date (YYYY-MM-DD)",
        "payment_amount": "Base rent for a SINGLE payment period as a plain number",
        "payment_frequency": "Billing cadence of the base rent: one of monthly, quarterly, annually",
    },
}

INBOUND_CLASSIFY_SYSTEM = (
    "You are a back-office assistant for a commercial property management team "
    "that triages inbound documents (emails and their attachments). Determine "
    "which single type best describes the document, then extract that type's "
    "fields so a human can route and pre-fill the matching record. Respond ONLY "
    "with a JSON object. Do not invent values.\n"
    "\n"
    "Document types:\n"
    "- vendor_invoice: a bill/invoice received from a vendor or supplier (AP).\n"
    "- insurance_certificate: a certificate of insurance (COI / ACORD form).\n"
    "- lease_amendment: an amendment, addendum, extension, or modification to an "
    "existing lease.\n"
    "- lease: a new/original lease agreement.\n"
    "- unknown: none of the above, or too ambiguous to classify confidently.\n"
    "\n"
    "Rules:\n"
    "- document_type must be exactly one of: vendor_invoice, "
    "insurance_certificate, lease_amendment, lease, unknown.\n"
    "- confidence must be exactly one of: high, medium, low.\n"
    "- reasoning must be one short sentence explaining the classification.\n"
    "- fields must be a JSON object containing ONLY the keys listed for the "
    "chosen document_type (an empty object for 'unknown'). Use null for any "
    "field you cannot determine.\n"
    "- Dates must be ISO 8601 (YYYY-MM-DD). Return monetary amounts as plain "
    "numbers with no currency symbols, commas, or thousands separators."
)


def _format_classify_fields() -> str:
    """Render the per-type field schema as a prompt block."""
    blocks: list[str] = []
    for doc_type, fields in INBOUND_CLASSIFY_FIELDS.items():
        lines = "\n".join(f"    - {k}: {v}" for k, v in fields.items())
        blocks.append(f"- {doc_type}:\n{lines}")
    return "\n".join(blocks)


async def classify_document(
    content: bytes,
    mime_type: str,
    *,
    text_content: str | None = None,
) -> dict[str, Any]:
    """Classify an inbound document and extract type-specific fields.

    Returns a dict with the keys ``document_type`` (one of
    :data:`INBOUND_DOCUMENT_TYPES`), ``confidence`` (high/medium/low),
    ``reasoning`` (a short string) and ``fields`` (the extracted values for the
    detected type). All values are *suggestions* for human review; callers never
    auto-commit.

    For PDFs and images the raw bytes are sent inline (Gemini reads them
    natively). For formats Gemini cannot parse directly (e.g. Word/text
    documents), the caller extracts plain text first and passes it as
    ``text_content``; that text is sent in place of the inline document.
    """
    prompt = (
        "Classify the following inbound document and extract the fields for the "
        "detected type. Return a single JSON object with exactly these keys: "
        "document_type, confidence, reasoning, fields.\n\n"
        "DOCUMENT TYPES AND THEIR FIELDS:\n"
        f"{_format_classify_fields()}\n"
    )
    segments = await _document_segments(
        content, mime_type, text_content, document_label="DOCUMENT TEXT"
    )
    texts = await _generate_over_segments(
        [{"text": prompt}], segments, system_instruction=INBOUND_CLASSIFY_SYSTEM
    )
    results = []
    for text in texts:
        try:
            results.append(_normalize_classification(_parse_json_object(text)))
        except AIRequestError as exc:  # tolerate one malformed segment
            logger.warning("Discarding unparseable classification segment: %s", exc)
    if not results:
        raise AIRequestError("AI provider did not return valid JSON")
    return _merge_classifications(results)


def _merge_classifications(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the best-supported classification and merge its fields.

    The document type is decided by the segment that identified a known type
    with the highest confidence (documents lead with their identifying header),
    and fields from every segment agreeing on that type are merged so values
    that only appear later in a large document are still populated.
    """
    if len(results) == 1:
        return results[0]
    order = {conf: i for i, conf in enumerate(_CLASSIFY_CONFIDENCES)}
    known = [r for r in results if r["document_type"] != "unknown"] or results
    best = min(known, key=lambda r: order.get(r["confidence"], 99))
    same_type = [r for r in results if r["document_type"] == best["document_type"]]
    return {
        "document_type": best["document_type"],
        "confidence": best["confidence"],
        "reasoning": best["reasoning"],
        "fields": _merge_segment_results([r["fields"] for r in same_type]),
    }

def _normalize_classification(parsed: dict[str, Any]) -> dict[str, Any]:
    """Coerce raw model output into a clean classification result.

    Unknown/invalid document types collapse to ``unknown`` and the returned
    ``fields`` are restricted to the keys defined for the detected type so
    callers can map them onto the right record without surprises.
    """
    doc_type = str(parsed.get("document_type") or "").strip().lower()
    if doc_type not in INBOUND_DOCUMENT_TYPES:
        doc_type = "unknown"

    confidence = str(parsed.get("confidence") or "").strip().lower()
    if confidence not in _CLASSIFY_CONFIDENCES:
        confidence = "low"

    allowed = INBOUND_CLASSIFY_FIELDS.get(doc_type, {})
    raw_fields = parsed.get("fields")
    fields: dict[str, Any] = {}
    if isinstance(raw_fields, dict):
        fields = {k: raw_fields.get(k) for k in allowed if k in raw_fields}

    return {
        "document_type": doc_type,
        "confidence": confidence,
        "reasoning": str(parsed.get("reasoning") or "").strip()[:500],
        "fields": fields,
    }


SUMMARY_SYSTEM = (
    "You are an operations analyst for a commercial property management team. "
    "Write a concise, professional briefing in Markdown from the structured data "
    "provided. Lead with the most time-sensitive items, covering, where present: "
    "lease notice deadlines, upcoming lease expirations, overdue maintenance, "
    "expiring certificates of insurance (COIs), upcoming HVAC service/contract "
    "renewals, and past-due accounts-payable (vendor bills). Be specific and do "
    "not invent data beyond what is given."
)


async def generate_summary_narrative(period_label: str, data: dict[str, Any]) -> str:
    """Generate a narrative summary report from aggregated stats.

    ``data`` is a JSON-serialisable dict of pre-aggregated figures (counts,
    upcoming lease notice/expiration items, overdue tickets, expiring COIs,
    HVAC renewals, past-due payables, etc).
    """
    blob = json.dumps(data, default=str)
    if len(blob) > MAX_TEXT_CHARS:
        blob = blob[:MAX_TEXT_CHARS]
    prompt = (
        f"Write a portfolio operations summary for the period: {period_label}.\n"
        "Use the following structured data (JSON):\n"
        f"{blob}\n"
    )
    parts = [{"text": prompt}]
    return await _generate(parts, system_instruction=SUMMARY_SYSTEM, temperature=0.4)


# ── AI-recommended actions ────────────────────────────────────────────────────

RECOMMENDED_ACTIONS_SYSTEM = (
    "You are an operations analyst for a commercial property management team. "
    "From the structured portfolio data provided, produce a prioritised list of "
    "concrete, actionable next steps the team should take this period. Focus on "
    "time-sensitive risk and deadline items: lease notice deadlines and "
    "expirations, overdue maintenance, expiring certificates of insurance (COIs), "
    "upcoming HVAC service/contract renewals, and past-due vendor bills. "
    "Return ONLY a JSON object of the form "
    '{"actions": [{"title": "...", "detail": "...", "priority": "high|medium|low", '
    '"category": "lease|insurance|hvac|accounts_payable|maintenance|other"}]}. '
    "Order actions from highest to lowest priority. Keep each title short (under "
    "120 characters) and the detail to one or two sentences. Do not invent data "
    "beyond what is given; if nothing requires action, return an empty list."
)

# Bound how many actions we surface so the prompt/response stay manageable.
MAX_RECOMMENDED_ACTIONS = 12

_ACTION_PRIORITIES = ("high", "medium", "low")


async def generate_recommended_actions(
    period_label: str, data: dict[str, Any]
) -> list[dict[str, Any]]:
    """Generate a structured list of AI-recommended actions from aggregated stats.

    Returns a list of ``{"title", "detail", "priority", "category"}`` dicts,
    ordered highest-priority first. Defensive against malformed model output.
    """
    blob = json.dumps(data, default=str)
    if len(blob) > MAX_TEXT_CHARS:
        blob = blob[:MAX_TEXT_CHARS]
    prompt = (
        f"Recommend prioritised actions for the period: {period_label}.\n"
        "Use the following structured data (JSON):\n"
        f"{blob}\n"
    )
    parts = [{"text": prompt}]
    raw = await _generate(
        parts,
        system_instruction=RECOMMENDED_ACTIONS_SYSTEM,
        json_response=True,
        temperature=0.3,
    )
    parsed = _parse_json_object(raw)
    return _normalize_actions(parsed.get("actions"))


def _normalize_actions(actions: Any) -> list[dict[str, Any]]:
    """Coerce model output into a clean, bounded list of action dicts."""
    if not isinstance(actions, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for item in actions:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        priority = str(item.get("priority") or "").strip().lower()
        if priority not in _ACTION_PRIORITIES:
            priority = "medium"
        category = str(item.get("category") or "other").strip().lower() or "other"
        cleaned.append(
            {
                "title": title[:200],
                "detail": str(item.get("detail") or "").strip()[:500],
                "priority": priority,
                "category": category,
            }
        )
        if len(cleaned) >= MAX_RECOMMENDED_ACTIONS:
            break
    return cleaned


def actions_to_markdown(actions: list[dict[str, Any]]) -> str:
    """Render recommended actions as a Markdown section for emails/exports."""
    if not actions:
        return ""
    lines = ["## AI-Recommended Actions", ""]
    for action in actions:
        priority = str(action.get("priority") or "medium").upper()
        title = str(action.get("title") or "").strip()
        detail = str(action.get("detail") or "").strip()
        bullet = f"- **[{priority}] {title}**"
        if detail:
            bullet += f" — {detail}"
        lines.append(bullet)
    return "\n".join(lines)


# ── Portfolio Q&A (RAG over lease document chunks) ───────────────────────────

PORTFOLIO_QA_SYSTEM = (
    "You are a commercial real-estate portfolio analyst assistant. Answer the "
    "user's question using ONLY the supplied lease document excerpts. Each "
    "excerpt is prefixed with a numbered citation id like [1], [2].\n"
    "\n"
    "Rules:\n"
    "- Ground every factual claim in the excerpts and cite the supporting "
    "excerpt id(s) inline in square brackets, e.g. 'the lease expires in 2026 "
    "[2].'. Cite only excerpts you actually relied on; never cite an id that was "
    "not provided.\n"
    "- NEVER invent or guess lease terms, dates, figures, party names, or "
    "clauses. Only state what the excerpts support. If you are unsure, say so.\n"
    "- If the excerpts do not contain enough information to answer, say that "
    "plainly and, when useful, name what is missing — do not speculate.\n"
    "- Do not perform arithmetic or aggregation (totals, averages, counts) "
    "unless every value needed is present in the excerpts; if some are missing, "
    "report the figures you can cite and note the result is incomplete.\n"
    "- When excerpts conflict, surface the discrepancy and cite each side rather "
    "than silently picking one.\n"
    "- Quote amounts, dates, and rates exactly as written in the excerpts "
    "(including currency and units); do not reformat or round them.\n"
    "- Be concise and use Markdown.\n"
    "\n"
    "Example:\n"
    "Excerpt [1] 'Base rent is $42,000 per year through 2026.'\n"
    "Question: 'What is the annual base rent?'\n"
    "Answer: 'The annual base rent is $42,000 [1].'"
)

# Cap how many excerpts (and how much of each) we feed the model so the prompt
# stays bounded regardless of how many chunks were retrieved.
MAX_QA_CONTEXT_CHUNKS = 12
MAX_QA_CHUNK_CHARS = 4000

# ── Portfolio assistant (RAG Q&A, Phase 3) ────────────────────────────────────

# Standard message used to decline questions the portfolio context cannot
# answer. Kept as a constant so the system prompt and the deterministic
# no-context guard stay in sync (and so callers/tests can assert on it).
ASSISTANT_REFUSAL = (
    "I can only answer questions about your organization's portfolio, and I "
    "couldn't find any information in your records to answer that."
)

PORTFOLIO_ASSISTANT_SYSTEM = (
    "You are a portfolio assistant for a commercial property management team. "
    "Answer the user's question using ONLY the numbered context passages "
    "provided. The context is drawn from the team's own records across the whole "
    "portfolio — offices, leases, lease documents, lease abstracts, landlords, "
    "vendors, management companies, maintenance tickets, HVAC contracts, office "
    "transitions, insurance certificates, rental units, residents, resident "
    "leases, rent charges, property owners, owner distributions, vendor bills "
    "(accounts payable), customer invoices (accounts receivable), bank "
    "accounts, budgets, inspections, and vacancy listings.\n"
    "\n"
    "Rules:\n"
    "- Base every statement on the context. Never invent facts, figures, names, "
    "or dates that are not present in the passages, and never rely on outside "
    "knowledge.\n"
    "- Answer ONLY questions about this organization's portfolio that the "
    "supplied passages address. If the question is unrelated to the portfolio "
    "(for example general knowledge, current events, coding help, math puzzles, "
    "opinions, or small talk), or the passages do not contain information that "
    "answers it, you MUST decline. Do not answer from your own knowledge, and "
    "do not speculate.\n"
    f"- When you decline, respond with exactly: '{ASSISTANT_REFUSAL}' You may "
    "add one short sentence naming the portfolio information that is missing, "
    "but never provide an out-of-scope answer.\n"
    "- Cite the passages you rely on inline using square-bracket numbers that "
    "match the passage numbers, e.g. [1] or [2][3]. Cite only passages you "
    "actually used and never cite a number that was not provided.\n"
    "- Do not compute totals, averages, or counts unless every value needed "
    "appears in the passages; when some are missing, report the values you can "
    "cite and note the answer is partial.\n"
    "- When passages disagree, surface the conflict and cite each side instead "
    "of silently choosing one.\n"
    "- Quote amounts, dates, and identifiers exactly as written; do not reformat "
    "or round them.\n"
    "- Be concise and factual. Use Markdown when it aids readability.\n"
    "\n"
    "Example (in scope):\n"
    "Passage [1] 'Office 42 (Galaxy Tower) is managed by Orbit Realty.'\n"
    "Question: 'Who manages office 42?'\n"
    "Answer: 'Office 42 (Galaxy Tower) is managed by Orbit Realty [1].'\n"
    "\n"
    "Example (out of scope):\n"
    "Passage [1] 'Office 42 (Galaxy Tower) is managed by Orbit Realty.'\n"
    "Question: 'What is the capital of France?'\n"
    f"Answer: '{ASSISTANT_REFUSAL}'"
)

# Bound the context assembled into the assistant prompt.
MAX_ASSISTANT_CONTEXT_CHARS = 24_000
MAX_ASSISTANT_PASSAGE_CHARS = 2_000


async def answer_portfolio_question(
    question: str,
    context_chunks: list[dict[str, Any]],
    *,
    temperature: float = 0.2,
) -> str:
    """Answer ``question`` grounded in retrieved lease document excerpts.

    ``context_chunks`` is an ordered list of dicts describing the retrieved
    excerpts. Each must carry an ``index`` (1-based citation id) and a textual
    body (``content`` or ``snippet``); ``lease_name`` and ``source_filename``
    are included in the prompt when present so the model can attribute claims.
    The returned Markdown answer cites excerpts inline by their ``index``.

    Raises :class:`AIUnavailableError` when no API key is configured so callers
    can degrade gracefully.
    """
    question = (question or "").strip()
    if not question:
        raise AIRequestError("A question is required.")

    blocks: list[str] = []
    for chunk in context_chunks[:MAX_QA_CONTEXT_CHUNKS]:
        idx = chunk.get("index")
        body = (chunk.get("content") or chunk.get("snippet") or "").strip()
        if idx is None or not body:
            continue
        lease_name = (chunk.get("lease_name") or "Unknown lease").strip()
        filename = (chunk.get("source_filename") or "").strip()
        header = f"[{idx}] Lease: {lease_name}"
        if filename:
            header += f" — Document: {filename}"
        blocks.append(f"{header}\n{body[:MAX_QA_CHUNK_CHARS]}")

    if not blocks:
        raise AIRequestError("No lease document excerpts were available to answer the question.")

    context = "\n\n".join(blocks)[:MAX_TEXT_CHARS]
    prompt = (
        f"QUESTION:\n{question}\n\n"
        "LEASE DOCUMENT EXCERPTS:\n"
        f"{context}\n\n"
        "Answer the question using only these excerpts and cite the excerpt "
        "id(s) you used in square brackets."
    )
    return await _generate(
        [{"text": prompt}],
        system_instruction=PORTFOLIO_QA_SYSTEM,
        temperature=temperature,
    )


# ── Natural-language report builder (Pro+) ────────────────────────────────────

REPORT_BUILDER_SYSTEM = (
    "You are a reporting assistant for a commercial property management system. "
    "Map the user's plain-English request onto ONE of the available datasets and "
    "return a JSON object describing which columns and filters to use. "
    "Respond ONLY with a JSON object with exactly these keys: dataset, columns, "
    "filters.\n"
    "\n"
    "Rules:\n"
    "- dataset MUST be one of the provided dataset ids. Pick the single best fit.\n"
    "- columns MUST be a list drawn only from that dataset's available column "
    "keys. Use an empty list to mean 'all columns'.\n"
    "- filters MUST be a JSON object whose keys are only that dataset's available "
    "filter keys, mapped to the requested value. Omit filters that are not "
    "requested. Use an empty object when no filters apply.\n"
    "- NEVER invent dataset ids, column keys, or filter keys. NEVER produce SQL "
    "or any free-form query."
)


def _format_report_datasets(datasets: list[dict[str, Any]]) -> str:
    """Render the dataset/column/filter schema as a prompt block."""
    blocks: list[str] = []
    for ds in datasets:
        cols = ", ".join(ds.get("columns", []))
        filt_parts = []
        for f in ds.get("filters", []):
            opts = f.get("options")
            label = f"{f['key']} ({f.get('type', 'text')}"
            if opts:
                label += f"; one of: {', '.join(map(str, opts))}"
            label += ")"
            filt_parts.append(label)
        filters = "; ".join(filt_parts) if filt_parts else "none"
        blocks.append(
            f"- {ds['dataset']} — {ds.get('title', ds['dataset'])}\n"
            f"    columns: {cols}\n"
            f"    filters: {filters}"
        )
    return "\n".join(blocks)


async def build_report_spec(
    prompt: str,
    datasets: list[dict[str, Any]],
) -> dict[str, Any]:
    """Turn a plain-English report request into a ``{dataset, columns, filters}`` draft.

    ``datasets`` is the safe schema describing the available datasets, their
    column keys and filter keys (see
    :func:`app.services.report_service.dataset_schema_for_prompt`). The model only
    ever sees these building blocks; it never emits SQL. The returned dict is a
    raw suggestion that the caller MUST validate against the real dataset config
    before use.
    """
    clean_prompt = (prompt or "").strip()
    if not clean_prompt:
        raise AIRequestError("A report request prompt is required.")

    user_prompt = (
        "AVAILABLE DATASETS:\n"
        f"{_format_report_datasets(datasets)}\n\n"
        "USER REQUEST:\n"
        f"{clean_prompt[:MAX_TEXT_CHARS]}"
    )
    text = await _generate(
        [{"text": user_prompt}],
        system_instruction=REPORT_BUILDER_SYSTEM,
        json_response=True,
    )
    parsed = _parse_json_object(text)

    dataset = str(parsed.get("dataset") or "").strip()
    raw_columns = parsed.get("columns")
    columns = [str(c) for c in raw_columns] if isinstance(raw_columns, list) else []
    raw_filters = parsed.get("filters")
    filters = raw_filters if isinstance(raw_filters, dict) else {}

    return {"dataset": dataset, "columns": columns, "filters": filters}


# ── Natural-language data query (structured, Pro+) ────────────────────────────

DATA_QUERY_SYSTEM = (
    "You translate a plain-English question about a property-management database "
    "into ONE structured query spec. You never write SQL. Respond ONLY with a "
    "JSON object with these keys: entity, select, filters, aggregate, "
    "aggregate_column, group_by, order_by, limit.\n"
    "\n"
    "Rules:\n"
    "- entity MUST be exactly one of the provided entity names. Pick the single "
    "best fit for the question.\n"
    "- select is a list of column names from that entity (empty list = all "
    "columns). Only use it for 'show/list/which' questions.\n"
    "- filters is a list of {column, op, value}. op is one of: eq, ne, gt, gte, "
    "lt, lte, contains, starts_with, in, is_null, not_null. Use 'contains' for "
    "partial text matches, 'in' with a list of values, and omit 'value' for "
    "is_null/not_null. Only reference columns that exist on the chosen entity.\n"
    "- For 'how many/count/total number' questions set aggregate to 'count'. For "
    "'total/sum/average/max/min of <numeric field>' set aggregate to "
    "sum|avg|min|max and aggregate_column to that numeric column.\n"
    "- group_by is a list of columns; only use it with an aggregate for "
    "'... by <field>' / 'per <field>' questions.\n"
    "- order_by is {column, direction} where direction is asc or desc. limit is "
    "an integer (default 100, max 500).\n"
    "- NEVER invent entity, column, or operator names. NEVER produce SQL."
)


def _format_query_catalog(entities: list[dict[str, Any]]) -> str:
    """Render the data-query catalog as a compact prompt block."""
    blocks: list[str] = []
    for ent_cfg in entities:
        cols = ", ".join(
            f"{c['name']} ({c['kind']})" for c in ent_cfg.get("columns", [])
        )
        blocks.append(
            f"- {ent_cfg['entity']} — {ent_cfg.get('title', ent_cfg['entity'])}\n"
            f"    columns: {cols}"
        )
    return "\n".join(blocks)


async def build_data_query_spec(
    question: str,
    entities: list[dict[str, Any]],
) -> dict[str, Any]:
    """Map a plain-English question onto a raw structured query spec.

    ``entities`` is the safe catalog produced by
    :func:`app.services.data_query_service.catalog_for_prompt` — the model only
    ever sees entity/column names and kinds, never the ORM or SQL. The returned
    dict is a raw suggestion the caller MUST validate against the real catalog
    (via ``data_query_service.validate_spec``) before executing.
    """
    clean = (question or "").strip()
    if not clean:
        raise AIRequestError("A data-query question is required.")

    user_prompt = (
        "AVAILABLE ENTITIES:\n"
        f"{_format_query_catalog(entities)}\n\n"
        "USER QUESTION:\n"
        f"{clean[:MAX_TEXT_CHARS]}"
    )
    text = await _generate(
        [{"text": user_prompt}],
        system_instruction=DATA_QUERY_SYSTEM,
        json_response=True,
        model="fast",
    )
    parsed = _parse_json_object(text)
    return parsed if isinstance(parsed, dict) else {}


# ── In-app assistant: intent parsing (Pro+) ───────────────────────────────────

# The constrained set of intents the assistant can recognise, mapped to the
# parameter keys each one accepts. The model MUST choose one of these intents
# and never invent new ones; execution always happens through existing typed
# endpoints, never raw actions.
ASSISTANT_INTENTS: dict[str, list[str]] = {
    "create_ticket": ["subject", "office_number", "priority"],
    "navigate": ["destination"],
    "search": ["query"],
    "unknown": [],
}

# Allowed navigation destinations (intent="navigate" → params.destination).
ASSISTANT_NAV_DESTINATIONS = (
    "offices",
    "leases",
    "leases_expiring",
    "maintenance_tickets",
    "vendors",
    "landlords",
    "transitions",
    "hvac_contracts",
    "reports",
    "saved_reports",
)

ASSISTANT_PRIORITIES = ("low", "medium", "high")

ASSISTANT_SYSTEM = (
    "You are an in-app assistant for a commercial property management system. "
    "Map the user's request onto ONE recognised intent and return a JSON object "
    "with exactly these keys: intent, params.\n"
    "\n"
    "Recognised intents and their params:\n"
    "- create_ticket: { subject (string), office_number (integer or null), "
    "priority (one of low|medium|high) } — for requests to open a maintenance "
    "ticket/work order.\n"
    "- navigate: { destination } where destination is exactly one of: "
    f"{', '.join(ASSISTANT_NAV_DESTINATIONS)}. Use leases_expiring for requests "
    "about leases expiring soon/this quarter/this year.\n"
    "- search: { query (string) } — for finding a specific named record.\n"
    "- unknown: { } — when the request matches none of the above.\n"
    "\n"
    "Rules:\n"
    "- intent MUST be one of: create_ticket, navigate, search, unknown.\n"
    "- Only include params for the chosen intent. Never invent destinations, "
    "priorities, routes, or SQL."
)


def _normalize_intent(parsed: dict[str, Any]) -> dict[str, Any]:
    """Coerce raw model output into a clean ``{intent, params}`` result."""
    intent = str(parsed.get("intent") or "").strip().lower()
    if intent not in ASSISTANT_INTENTS:
        intent = "unknown"

    raw_params = parsed.get("params")
    raw_params = raw_params if isinstance(raw_params, dict) else {}
    allowed = ASSISTANT_INTENTS[intent]
    params: dict[str, Any] = {}

    if intent == "create_ticket":
        subject = raw_params.get("subject")
        params["subject"] = str(subject).strip() if subject else ""
        office_number = raw_params.get("office_number")
        try:
            params["office_number"] = int(office_number) if office_number is not None else None
        except (TypeError, ValueError):
            params["office_number"] = None
        priority = str(raw_params.get("priority") or "").strip().lower()
        params["priority"] = priority if priority in ASSISTANT_PRIORITIES else "medium"
    elif intent == "navigate":
        destination = str(raw_params.get("destination") or "").strip().lower()
        if destination not in ASSISTANT_NAV_DESTINATIONS:
            # Unknown destination collapses the whole intent to unknown.
            return {"intent": "unknown", "params": {}}
        params["destination"] = destination
    elif intent == "search":
        params["query"] = str(raw_params.get("query") or "").strip()
    else:
        params = {k: raw_params.get(k) for k in allowed if k in raw_params}

    return {"intent": intent, "params": params}


async def parse_assistant_intent(prompt: str) -> dict[str, Any]:
    """Map a plain-English request onto a constrained ``{intent, params}`` result.

    The returned intent is always one of :data:`ASSISTANT_INTENTS`. Callers map
    it onto an existing typed endpoint/route and enforce the caller's own
    permissions — this function never executes anything itself.
    """
    clean_prompt = (prompt or "").strip()
    if not clean_prompt:
        raise AIRequestError("An assistant prompt is required.")

    text = await _generate(
        [{"text": clean_prompt[:MAX_TEXT_CHARS]}],
        system_instruction=ASSISTANT_SYSTEM,
        json_response=True,
        model="fast",
    )
    return _normalize_intent(_parse_json_object(text))


async def answer_assistant_question(
    question: str,
    context_blocks: list[dict[str, Any]],
) -> str:
    """Answer ``question`` grounded in the supplied retrieved ``context_blocks``.

    Each block is a dict with at least ``title`` and ``content`` keys (as
    returned by :func:`app.services.knowledge_service.retrieve`). Passages are
    numbered so the model can cite them; the answer is returned as Markdown text.
    Raises :class:`AIUnavailableError` when Gemini is not configured.
    """
    question = (question or "").strip()
    if not question:
        raise AIRequestError("The question was empty.")

    lines: list[str] = []
    used = 0
    for idx, block in enumerate(context_blocks, start=1):
        title = _clean_inline(str(block.get("title") or "Untitled"))
        body = _clean_inline(str(block.get("content") or ""))[:MAX_ASSISTANT_PASSAGE_CHARS]
        passage = f"[{idx}] {title}\n{body}"
        if used + len(passage) > MAX_ASSISTANT_CONTEXT_CHARS:
            break
        lines.append(passage)
        used += len(passage)

    context = "\n\n".join(lines) if lines else ""
    # No org-scoped passages were retrieved: the question is not answerable from
    # this organization's portfolio, so deny it deterministically rather than
    # letting the model improvise from outside knowledge.
    if not context:
        return ASSISTANT_REFUSAL
    prompt = (
        "Context passages:\n"
        f"{context}\n"
        "\n"
        f"Question: {question}\n"
        "\n"
        "Answer the question using only the context above, citing passages by "
        "their number. If the context does not answer the question, decline as "
        "instructed."
    )
    return await _generate(
        [{"text": prompt}], system_instruction=PORTFOLIO_ASSISTANT_SYSTEM, temperature=0.2
    )


def _clean_inline(text: str) -> str:
    return " ".join((text or "").split())


# ── Embeddings (semantic document search) ─────────────────────────────────────

# Cap the number of texts embedded in a single batch request.
EMBED_BATCH_SIZE = 100


def _embed_endpoint(model: str) -> str:
    base = settings.GEMINI_API_BASE.rstrip("/")
    return f"{base}/models/{model}:batchEmbedContents"


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Return an embedding vector for each input string.

    Raises :class:`AIUnavailableError` when no API key is configured so callers
    can fall back to keyword search. The embedding model is configurable via
    ``GEMINI_EMBED_MODEL``.
    """
    if not embeddings_configured():
        provider = get_embedding_provider_name()
        raise AIUnavailableError(
            f"Embeddings are not configured for provider '{provider}'."
        )
    if not texts:
        return []

    provider = get_embedding_provider_name()
    model = get_embedding_model_name()
    vectors: list[list[float]] = []

    for start in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[start : start + EMBED_BATCH_SIZE]
        if provider == "gemini":
            url = _embed_endpoint(model)
            payload = {
                "requests": [
                    {
                        "model": f"models/{model}",
                        "content": {"parts": [{"text": (t or "")[:MAX_TEXT_CHARS]}]},
                    }
                    for t in batch
                ]
            }
            params = {"key": settings.GEMINI_API_KEY}
            headers = None
        else:
            base = (
                settings.OPENAI_API_BASE
                if provider == "openai"
                else settings.OPENROUTER_API_BASE
            )
            url = f"{base.rstrip('/')}/embeddings"
            payload = {
                "model": model,
                "input": [(text or "")[:MAX_TEXT_CHARS] for text in batch],
                "dimensions": settings.AI_EMBED_DIMENSIONS,
            }
            params = None
            headers = _openai_headers(provider)
        try:
            resp = await _post_with_retry(
                url, params=params, headers=headers, json=payload
            )
        except httpx.HTTPError as exc:
            logger.warning("Gemini embed request failed: %s", exc)
            raise AIRequestError(f"AI provider request failed: {exc}") from exc

        if resp.status_code != 200:
            detail = _safe_error_detail(resp)
            logger.warning("Gemini embed returned %s: %s", resp.status_code, detail)
            raise AIRequestError(f"AI provider error ({resp.status_code}): {detail}")

        try:
            data = resp.json()
            if provider == "gemini":
                embeddings = data["embeddings"]
                batch_vectors = [[float(v) for v in emb["values"]] for emb in embeddings]
            else:
                embeddings = sorted(data["data"], key=lambda item: item.get("index", 0))
                batch_vectors = [[float(v) for v in emb["embedding"]] for emb in embeddings]
            for vector in batch_vectors:
                if len(vector) != settings.AI_EMBED_DIMENSIONS:
                    raise AIRequestError(
                        f"Embedding provider returned {len(vector)} dimensions; "
                        f"expected {settings.AI_EMBED_DIMENSIONS}."
                    )
                vectors.append(vector)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Unexpected Gemini embed response shape: %s", exc)
            raise AIRequestError("AI provider returned an unexpected response") from exc

        # batchEmbedContents may report token usage; account for it when present
        # (input tokens only — embeddings have no generated output).
        _record_usage_metadata(data)

    return vectors
