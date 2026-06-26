"""Digital waiver helpers: merge-field rendering, hashing, and signed PDF.

Kept separate from the router so the rendering/hash/PDF logic can be unit-tested
without HTTP plumbing.
"""
from __future__ import annotations

import hashlib
import io
import re
from datetime import date, datetime
from html import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# The consent statement a signer must affirm. Capturing this verbatim with the
# signature is part of an ESIGN/UETA-compliant audit trail.
ESIGN_CONSENT_TEXT = (
    "By typing or drawing my signature and clicking \"Sign\", I agree to use an "
    "electronic signature, I consent to conduct this transaction electronically, "
    "and I intend my electronic signature to be the legal equivalent of my "
    "handwritten signature on this document."
)

_MERGE_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render_body(body: str, context: dict[str, str]) -> str:
    """Substitute ``{{merge_field}}`` placeholders, leaving unknown ones intact."""
    def repl(match: re.Match) -> str:
        key = match.group(1)
        value = context.get(key)
        return str(value) if value is not None else match.group(0)

    return _MERGE_RE.sub(repl, body)


def compute_document_hash(text: str) -> str:
    """Return the SHA-256 hex digest of the rendered document text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_merge_context(*, recipient_name: str | None, organization_name: str | None) -> dict[str, str]:
    name = recipient_name or "Recipient"
    return {
        "recipient_name": name,
        "signer_name": name,
        "organization_name": organization_name or "the Organization",
        "date": date.today().strftime("%B %d, %Y"),
    }


def generate_signed_pdf(
    *,
    title: str,
    body: str,
    document_hash: str,
    signer_name: str,
    signer_email: str | None,
    signature_type: str,
    signature_data: str,
    consent_text: str | None,
    signed_at: datetime | None,
    ip_address: str | None,
    user_agent: str | None,
) -> bytes:
    """Render the signed waiver plus an audit-trail page to a PDF byte string."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("WTitle", parent=styles["Heading1"], fontSize=16, spaceAfter=12)
    body_style = ParagraphStyle("WBody", parent=styles["Normal"], fontSize=10, leading=14, spaceAfter=8)
    label_style = ParagraphStyle("WLabel", parent=styles["Heading2"], fontSize=12, spaceBefore=12, spaceAfter=6)
    small_style = ParagraphStyle("WSmall", parent=styles["Normal"], fontSize=8, textColor=colors.grey)

    elements: list = [Paragraph(escape(title), title_style)]
    for para in body.split("\n"):
        if para.strip():
            elements.append(Paragraph(escape(para), body_style))
        else:
            elements.append(Spacer(1, 6))

    elements.append(Spacer(1, 18))
    elements.append(Paragraph("Electronic Signature", label_style))

    signed_str = signed_at.strftime("%Y-%m-%d %H:%M:%S UTC") if signed_at else "—"
    audit_rows = [
        ["Signer name", signer_name or "—"],
        ["Signer email", signer_email or "—"],
        ["Signature method", signature_type or "—"],
        ["Signed at", signed_str],
        ["IP address", ip_address or "—"],
        ["User agent", (user_agent or "—")[:120]],
        ["Document SHA-256", document_hash],
    ]
    if signature_type == "typed":
        audit_rows.insert(0, ["Signature", signature_data])

    table = Table(audit_rows, colWidths=[1.6 * inch, 4.8 * inch])
    table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555555")),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")),
            ]
        )
    )
    elements.append(table)

    if consent_text:
        elements.append(Spacer(1, 12))
        elements.append(Paragraph("Consent", label_style))
        elements.append(Paragraph(escape(consent_text), small_style))

    doc.build(elements)
    return buffer.getvalue()
