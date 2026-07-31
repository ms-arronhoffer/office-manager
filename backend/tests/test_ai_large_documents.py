"""Tests for large-document handling in the AI pipeline.

Covers the segmentation strategy that lets documents up to
``AI_MAX_FILE_SIZE_MB`` be processed: long text is split into overlapping
model-sized chunks, oversized PDFs prefer their text layer and fall back to
page-range splitting, and the per-segment results are merged so values that only
appear late in a document still get populated.
"""
import io

import pytest

from app.config import settings
from app.services import ai_service
from app.services import document_extraction as de


def _pdf_bytes(pages: int, text: str = "Lease clause text.") -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ── Text segmentation ────────────────────────────────────────────────────────

def test_split_text_returns_single_chunk_when_small():
    assert ai_service._split_text("hello") == ["hello"]
    assert ai_service._split_text("   ") == []


def test_split_text_overlaps_and_covers_whole_document():
    text = "x" * (ai_service.MAX_TEXT_CHARS * 2)
    chunks = ai_service._split_text(text)
    assert len(chunks) > 1
    assert all(len(c) <= ai_service.MAX_TEXT_CHARS for c in chunks)
    step = ai_service.MAX_TEXT_CHARS - ai_service.SEGMENT_OVERLAP_CHARS
    # Consecutive chunks overlap, and together they reach the end of the text.
    assert step * (len(chunks) - 1) + len(chunks[-1]) == len(text)


def test_split_text_is_bounded():
    text = "y" * (ai_service.MAX_TEXT_CHARS * (ai_service.MAX_DOCUMENT_SEGMENTS + 5))
    assert len(ai_service._split_text(text)) == ai_service.MAX_DOCUMENT_SEGMENTS


@pytest.mark.asyncio
async def test_document_segments_labels_parts():
    text = "z" * (ai_service.MAX_TEXT_CHARS + 10)
    segments = await ai_service._document_segments(
        b"", "text/plain", text, document_label="LEASE DOCUMENT TEXT"
    )
    assert len(segments) == 2
    assert "PART 1 OF 2" in segments[0][0]["text"]
    assert "PART 2 OF 2" in segments[1][0]["text"]


@pytest.mark.asyncio
async def test_document_segments_inline_for_small_binary():
    segments = await ai_service._document_segments(
        b"tiny image", "image/png", None, document_label="DOC"
    )
    assert len(segments) == 1
    assert "inlineData" in segments[0][0]


@pytest.mark.asyncio
async def test_small_text_pdf_prefers_extracted_text(monkeypatch):
    extracted = "R" * (ai_service.MAX_TEXT_CHARS + 10)

    async def fake_text(content):
        return extracted

    monkeypatch.setattr(ai_service, "_extract_pdf_text", fake_text)

    async def _fail(*args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("page splitting should not run when text exists")

    monkeypatch.setattr(ai_service, "_split_large_pdf", _fail)
    segments = await ai_service._document_segments(
        b"%PDF-1.4 small", "application/pdf", None, document_label="DOC"
    )
    assert len(segments) == 2
    assert "R" * 100 in segments[0][0]["text"]


@pytest.mark.asyncio
async def test_small_scanned_pdf_uses_ai_transcription(monkeypatch):
    async def fake_text(content):
        return ""

    monkeypatch.setattr(ai_service, "_extract_pdf_text", fake_text)

    async def fake_transcription(content):
        return "Transcribed lease text"

    monkeypatch.setattr(ai_service, "extract_pdf_text_with_ai", fake_transcription)
    segments = await ai_service._document_segments(
        b"%PDF-1.4 scan", "application/pdf", None, document_label="DOC"
    )
    assert len(segments) == 1
    assert "Transcribed lease text" in segments[0][0]["text"]


@pytest.mark.asyncio
async def test_document_segments_rejects_oversized_non_pdf():
    oversized = b"\x00" * (ai_service.MAX_DOCUMENT_BYTES + 1)
    with pytest.raises(ai_service.AIDocumentError):
        await ai_service._document_segments(
            oversized, "image/png", None, document_label="DOC"
        )


@pytest.mark.asyncio
async def test_document_segments_empty_when_no_document():
    assert await ai_service._document_segments(b"", "", None, document_label="DOC") == []


@pytest.mark.asyncio
async def test_large_pdf_prefers_extracted_text(monkeypatch):
    oversized = b"%PDF" + b"\x00" * ai_service.MAX_DOCUMENT_BYTES
    async def fake_text(content):
        return "R" * 5_000

    monkeypatch.setattr(ai_service, "_extract_pdf_text", fake_text)

    async def _fail(*args, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("page splitting should not run when text exists")

    monkeypatch.setattr(ai_service, "_split_large_pdf", _fail)
    segments = await ai_service._document_segments(
        oversized, "application/pdf", None, document_label="DOC"
    )
    assert len(segments) == 1
    assert "R" * 100 in segments[0][0]["text"]


@pytest.mark.asyncio
async def test_large_scanned_pdf_falls_back_to_page_split(monkeypatch):
    oversized = b"%PDF" + b"\x00" * ai_service.MAX_DOCUMENT_BYTES
    async def fake_text(content):
        return ""

    monkeypatch.setattr(ai_service, "_extract_pdf_text", fake_text)
    async def fake_transcription(content):
        return "Text from all scanned pages"

    monkeypatch.setattr(ai_service, "extract_pdf_text_with_ai", fake_transcription)
    segments = await ai_service._document_segments(
        oversized, "application/pdf", None, document_label="DOC"
    )
    assert len(segments) == 1
    assert "Text from all scanned pages" in segments[0][0]["text"]


@pytest.mark.asyncio
async def test_extract_pdf_text_rejects_sparse_page_coverage(monkeypatch):
    monkeypatch.setattr(
        de,
        "extract_pdf_pages",
        lambda content: ["\x11\x16\x15", "", "Readable lease clause " * 40],
    )
    assert await ai_service._extract_pdf_text(b"%PDF mixed") == ""


# ── PDF splitting ────────────────────────────────────────────────────────────

def test_split_pdf_covers_every_page():
    content = _pdf_bytes(9)
    parts = de.split_pdf(content, max_bytes=len(content), max_parts=8)
    assert parts
    from pypdf import PdfReader

    total_pages = sum(len(PdfReader(io.BytesIO(p)).pages) for p in parts)
    assert total_pages == 9


def test_split_pdf_respects_max_parts():
    content = _pdf_bytes(20)
    parts = de.split_pdf(content, max_bytes=1024, max_parts=2)
    assert len(parts) <= 2


def test_split_pdf_rejects_unreadable_input():
    with pytest.raises(de.DocumentExtractionError):
        de.split_pdf(b"not a pdf", max_bytes=1024, max_parts=4)


# ── Segment merging ──────────────────────────────────────────────────────────

def test_merge_segment_results_fills_gaps_from_later_segments():
    merged = ai_service._merge_segment_results(
        [
            {"lessor_name": "Acme", "payment_amount": None},
            {"lessor_name": "Other", "payment_amount": 5000, "currency": "USD"},
        ]
    )
    assert merged["lessor_name"] == "Acme"  # earlier segment wins
    assert merged["payment_amount"] == 5000  # gap filled from later segment
    assert merged["currency"] == "USD"


def test_merge_segment_results_merges_nested_objects():
    merged = ai_service._merge_segment_results(
        [
            {"renewal": {"summary": "One option", "notice_days": None}},
            {"renewal": {"summary": "", "notice_days": 90}},
        ]
    )
    assert merged["renewal"] == {"summary": "One option", "notice_days": 90}


def test_merge_gap_findings_keeps_missing_only_when_unanimous():
    seg_a = [
        {
            "category_key": "assignment",
            "gap_type": "missing",
            "severity": "high",
            "message": "m",
            "recommendation": "r",
        },
        {
            "category_key": "renewal",
            "gap_type": "missing",
            "severity": "high",
            "message": "m",
            "recommendation": "r",
        },
    ]
    seg_b = [
        {
            "category_key": "assignment",
            "gap_type": "missing",
            "severity": "medium",
            "message": "m",
            "recommendation": "r",
        },
        {
            "category_key": "deposit",
            "gap_type": "ambiguous",
            "severity": "low",
            "message": "m",
            "recommendation": "r",
        },
    ]
    merged = ai_service._merge_gap_findings([seg_a, seg_b])
    keys = {(g["category_key"], g["gap_type"]) for g in merged}
    assert ("assignment", "missing") in keys  # reported by every segment
    assert ("renewal", "missing") not in keys  # only one segment saw it
    assert ("deposit", "ambiguous") in keys  # local observations are unioned
    assignment = next(g for g in merged if g["category_key"] == "assignment")
    assert assignment["severity"] == "high"  # highest severity wins


def test_merge_classifications_prefers_confident_known_type():
    merged = ai_service._merge_classifications(
        [
            {
                "document_type": "unknown",
                "confidence": "low",
                "reasoning": "",
                "fields": {},
            },
            {
                "document_type": "vendor_invoice",
                "confidence": "high",
                "reasoning": "Invoice header",
                "fields": {"vendor_name": "Acme", "total_amount": None},
            },
            {
                "document_type": "vendor_invoice",
                "confidence": "low",
                "reasoning": "",
                "fields": {"total_amount": 1200},
            },
        ]
    )
    assert merged["document_type"] == "vendor_invoice"
    assert merged["confidence"] == "high"
    assert merged["fields"] == {"vendor_name": "Acme", "total_amount": 1200}


# ── Multi-segment generation ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_json_over_segments_merges_all_segments(monkeypatch):
    seen: list[str] = []

    async def fake_generate(parts, **kwargs):
        text = parts[-1]["text"]
        seen.append(text)
        if "PART 1" in text:
            return '{"lessor_name": "Acme"}'
        return '{"payment_amount": 4200}'

    monkeypatch.setattr(ai_service, "_generate", fake_generate)
    segments = await ai_service._document_segments(
        b"", "text/plain", "q" * (ai_service.MAX_TEXT_CHARS + 10), document_label="DOC"
    )
    merged = await ai_service._generate_json_over_segments([{"text": "prompt"}], segments)
    assert len(seen) == 2
    assert merged == {"lessor_name": "Acme", "payment_amount": 4200}


@pytest.mark.asyncio
async def test_generate_over_segments_tolerates_one_failed_segment(monkeypatch):
    calls = {"n": 0}

    async def fake_generate(parts, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ai_service.AIRequestError("boom")
        return '{"lessor_name": "Acme"}'

    monkeypatch.setattr(ai_service, "_generate", fake_generate)
    segments = await ai_service._document_segments(
        b"", "text/plain", "q" * (ai_service.MAX_TEXT_CHARS + 10), document_label="DOC"
    )
    merged = await ai_service._generate_json_over_segments([{"text": "prompt"}], segments)
    assert merged == {"lessor_name": "Acme"}


@pytest.mark.asyncio
async def test_generate_over_segments_raises_when_all_fail(monkeypatch):
    async def fake_generate(parts, **kwargs):
        raise ai_service.AIRequestError("boom")

    monkeypatch.setattr(ai_service, "_generate", fake_generate)
    segments = await ai_service._document_segments(
        b"", "text/plain", "q" * (ai_service.MAX_TEXT_CHARS + 10), document_label="DOC"
    )
    with pytest.raises(ai_service.AIRequestError):
        await ai_service._generate_json_over_segments([{"text": "prompt"}], segments)


# ── Upload ceiling ───────────────────────────────────────────────────────────

def test_ai_upload_ceiling_is_at_least_attachment_ceiling():
    assert settings.AI_MAX_FILE_SIZE_MB >= 75
    assert settings.AI_MAX_FILE_SIZE_MB >= settings.MAX_FILE_SIZE_MB


@pytest.mark.asyncio
async def test_read_document_rejects_upload_over_ai_limit(monkeypatch):
    """An oversized upload is rejected while streaming, before any model call."""
    from fastapi import HTTPException
    from starlette.datastructures import Headers, UploadFile

    from app.routers import ai as ai_router

    monkeypatch.setattr(settings, "AI_MAX_FILE_SIZE_MB", 1)
    upload = UploadFile(
        file=io.BytesIO(b"a" * (2 * 1024 * 1024)),
        filename="big.txt",
        headers=Headers({"content-type": "text/plain"}),
    )
    with pytest.raises(HTTPException) as exc:
        await ai_router._read_document(upload)
    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_read_document_accepts_document_within_ai_limit():
    from starlette.datastructures import Headers, UploadFile

    from app.routers import ai as ai_router

    payload = b"Lessor: Acme." * 1000
    upload = UploadFile(
        file=io.BytesIO(payload),
        filename="lease.txt",
        headers=Headers({"content-type": "text/plain"}),
    )
    content, mime_type = await ai_router._read_document(upload)
    assert content == payload
    assert mime_type == "text/plain"
