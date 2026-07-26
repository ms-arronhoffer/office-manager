"""Legal document catalog.

The platform's legal documents (Terms of Service, EULA, Privacy Policy,
Acceptable Use Policy, ...) are stored as plain Markdown files under
``app/legal/documents`` and indexed by ``app/legal/manifest.json``. This service
loads that manifest, reads the Markdown, and renders it to HTML on demand so the
documents can be updated by editing the files alone — no code change required.

The rendered content is trusted, first-party Markdown shipped with the
application; it is never derived from user input.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from html import escape
from pathlib import Path

_LEGAL_DIR = Path(__file__).resolve().parent.parent / "legal"
_MANIFEST_PATH = _LEGAL_DIR / "manifest.json"
_DOCUMENTS_DIR = _LEGAL_DIR / "documents"


@dataclass(frozen=True)
class LegalDocumentMeta:
    """Metadata about a legal document (no body)."""

    slug: str
    title: str
    version: str
    effective_date: str
    summary: str
    required_at_signup: bool


@dataclass(frozen=True)
class LegalDocument:
    """A legal document including its rendered body."""

    meta: LegalDocumentMeta
    markdown: str
    html: str


def _render_markdown(md_text: str) -> str:
    """Render trusted Markdown to an HTML fragment.

    Falls back to an HTML-escaped ``<pre>`` block if the optional ``markdown``
    dependency is unavailable, so callers always get safe HTML.
    """
    try:
        import markdown as _markdown
    except ImportError:  # pragma: no cover - dependency guard
        return f"<pre>{escape(md_text or '')}</pre>"
    return _markdown.markdown(
        md_text or "",
        extensions=["extra", "sane_lists", "nl2br"],
    )


@lru_cache(maxsize=1)
def _load_manifest() -> list[LegalDocumentMeta]:
    with _MANIFEST_PATH.open(encoding="utf-8") as fh:
        raw = json.load(fh)
    documents: list[LegalDocumentMeta] = []
    for entry in raw.get("documents", []):
        documents.append(
            LegalDocumentMeta(
                slug=entry["slug"],
                title=entry["title"],
                version=entry["version"],
                effective_date=entry.get("effective_date", entry["version"]),
                summary=entry.get("summary", ""),
                required_at_signup=bool(entry.get("required_at_signup", False)),
            )
        )
    return documents


def _manifest_by_slug() -> dict[str, tuple[LegalDocumentMeta, str]]:
    """Map slug -> (meta, markdown filename) from the manifest on disk."""
    with _MANIFEST_PATH.open(encoding="utf-8") as fh:
        raw = json.load(fh)
    mapping: dict[str, tuple[LegalDocumentMeta, str]] = {}
    for entry in raw.get("documents", []):
        meta = LegalDocumentMeta(
            slug=entry["slug"],
            title=entry["title"],
            version=entry["version"],
            effective_date=entry.get("effective_date", entry["version"]),
            summary=entry.get("summary", ""),
            required_at_signup=bool(entry.get("required_at_signup", False)),
        )
        mapping[meta.slug] = (meta, entry["file"])
    return mapping


def list_documents() -> list[LegalDocumentMeta]:
    """Return metadata for every legal document, in manifest order."""
    return list(_load_manifest())


def get_document(slug: str) -> LegalDocument | None:
    """Return a single legal document (metadata + rendered body), or ``None``."""
    entry = _manifest_by_slug().get(slug)
    if entry is None:
        return None
    meta, filename = entry
    # Guard against path traversal: only allow files that live directly inside
    # the documents directory.
    path = (_DOCUMENTS_DIR / filename).resolve()
    if path.parent != _DOCUMENTS_DIR.resolve() or not path.is_file():
        return None
    md_text = path.read_text(encoding="utf-8")
    return LegalDocument(meta=meta, markdown=md_text, html=_render_markdown(md_text))


def current_versions() -> dict[str, str]:
    """Return a ``slug -> version`` map for all documents (acceptance record)."""
    return {doc.slug: doc.version for doc in _load_manifest()}


def required_documents() -> list[LegalDocumentMeta]:
    """Return the documents that must be accepted to create an organization."""
    return [doc for doc in _load_manifest() if doc.required_at_signup]
