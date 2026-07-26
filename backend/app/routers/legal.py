"""Public read-only API for the platform's legal documents.

These endpoints are unauthenticated: the Terms of Service, EULA, Privacy Policy,
and Acceptable Use Policy must be viewable by prospective customers on the
marketing site and during signup, before any account exists.
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.services import legal_service

router = APIRouter()


class LegalDocumentMetaSchema(BaseModel):
    slug: str
    title: str
    version: str
    effective_date: str
    summary: str
    required_at_signup: bool


class LegalDocumentSchema(LegalDocumentMetaSchema):
    html: str
    markdown: str


@router.get("", response_model=list[LegalDocumentMetaSchema])
async def list_legal_documents() -> list[LegalDocumentMetaSchema]:
    """List all legal documents (metadata only), in display order."""
    return [
        LegalDocumentMetaSchema(
            slug=doc.slug,
            title=doc.title,
            version=doc.version,
            effective_date=doc.effective_date,
            summary=doc.summary,
            required_at_signup=doc.required_at_signup,
        )
        for doc in legal_service.list_documents()
    ]


@router.get("/{slug}", response_model=LegalDocumentSchema)
async def get_legal_document(slug: str) -> LegalDocumentSchema:
    """Return a single legal document, including its rendered HTML body."""
    doc = legal_service.get_document(slug)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Legal document not found"
        )
    return LegalDocumentSchema(
        slug=doc.meta.slug,
        title=doc.meta.title,
        version=doc.meta.version,
        effective_date=doc.meta.effective_date,
        summary=doc.meta.summary,
        required_at_signup=doc.meta.required_at_signup,
        html=doc.html,
        markdown=doc.markdown,
    )
