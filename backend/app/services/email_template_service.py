"""Resolve, render and brand an outgoing email.

A send site asks for a ``template_key`` and a context; this module decides
whether the organization has overridden that message, substitutes the merge
fields, and wraps the result in the organization's branding.

The rules are deliberately forgiving, because mail must never fail to send:

* no override, or an inactive one, falls back to the built-in copy;
* an unknown ``{{placeholder}}`` is left visible rather than raising, so a typo
  shows up in a preview instead of silently blanking a sentence;
* absent branding produces the same neutral layout the product shipped with.
"""

from __future__ import annotations

import html
import re
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_branding import (
    DEFAULT_ACCENT_COLOR,
    DEFAULT_HEADER_COLOR,
    EmailBranding,
    EmailTemplate,
)
from app.models.organization import Organization
from app.services import email_catalog

_MERGE_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


class RenderedEmail:
    """A subject and body ready to hand to the mail client."""

    def __init__(self, subject: str, html_body: str, *, customized: bool):
        self.subject = subject
        self.html_body = html_body
        # True when the org's own copy was used, which the preview surfaces.
        self.customized = customized


def substitute(text: str, context: dict) -> str:
    """Replace ``{{field}}`` with its value, leaving unknown fields visible."""
    def repl(match: re.Match) -> str:
        value = context.get(match.group(1))
        return "" if value is None else str(value)

    return _MERGE_RE.sub(repl, text or "")


def unknown_fields(text: str, template_key: str) -> list[str]:
    """Placeholders in ``text`` that this template does not provide.

    Surfaced in the editor so an admin finds out about a typo while writing,
    not after a landlord receives a sentence with a gap in it.
    """
    definition = email_catalog.get(template_key)
    allowed = {f.name for f in definition.merge_fields} if definition else set()
    used = {m.group(1) for m in _MERGE_RE.finditer(text or "")}
    return sorted(used - allowed)


async def get_branding(
    db: AsyncSession, organization_id: uuid.UUID | None
) -> EmailBranding | None:
    if organization_id is None:
        return None
    return (
        await db.execute(
            select(EmailBranding).where(
                EmailBranding.organization_id == organization_id,
                EmailBranding.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()


async def get_override(
    db: AsyncSession, organization_id: uuid.UUID | None, template_key: str
) -> EmailTemplate | None:
    if organization_id is None:
        return None
    return (
        await db.execute(
            select(EmailTemplate).where(
                EmailTemplate.organization_id == organization_id,
                EmailTemplate.template_key == template_key,
            )
        )
    ).scalar_one_or_none()


async def organization_name(
    db: AsyncSession, organization_id: uuid.UUID | None
) -> str:
    if organization_id is None:
        return "Your organization"
    org = await db.get(Organization, organization_id)
    return org.name if org else "Your organization"


def wrap(
    body_html: str,
    *,
    branding: EmailBranding | None,
    org_name: str,
    preheader: str = "",
) -> str:
    """Apply the organization's header, signature and footer to a body."""
    header_color = (branding.header_color if branding else None) or DEFAULT_HEADER_COLOR
    accent = (branding.accent_color if branding else None) or DEFAULT_ACCENT_COLOR
    logo = branding.logo_url if branding else None
    signature = branding.signature if branding else None
    footer = (branding.footer_text if branding else None) or (
        f"This is an automated message from {html.escape(org_name)}."
    )
    postal = branding.postal_address if branding else None

    masthead = (
        f'<img src="{html.escape(logo)}" alt="{html.escape(org_name)}" '
        f'style="max-height:44px;max-width:220px;display:block;" />'
        if logo
        else f'<span style="color:#ffffff;font-size:18px;font-weight:600;">'
        f"{html.escape(org_name)}</span>"
    )

    signature_block = (
        f'<p style="margin:24px 0 0;color:#37474f;white-space:pre-line;">'
        f"{html.escape(signature)}</p>"
        if signature
        else ""
    )
    postal_block = (
        f'<div style="margin-top:8px;white-space:pre-line;">{html.escape(postal)}</div>'
        if postal
        else ""
    )

    return f"""<!DOCTYPE html>
<html>
  <body style="margin:0;padding:0;background:#f4f5f6;font-family:Segoe UI,Helvetica,Arial,sans-serif;">
    <span style="display:none;max-height:0;overflow:hidden;">{html.escape(preheader)}</span>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f5f6;padding:24px 0;">
      <tr>
        <td align="center">
          <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:600px;max-width:100%;background:#ffffff;border-radius:8px;overflow:hidden;">
            <tr>
              <td style="background:{html.escape(header_color)};padding:20px 24px;">{masthead}</td>
            </tr>
            <tr>
              <td style="padding:24px;color:#16191f;font-size:15px;line-height:1.6;border-left:4px solid {html.escape(accent)};">
                {body_html}
                {signature_block}
              </td>
            </tr>
            <tr>
              <td style="padding:16px 24px;background:#fafafa;color:#687078;font-size:12px;line-height:1.5;">
                <div style="white-space:pre-line;">{html.escape(footer)}</div>
                {postal_block}
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""


async def render(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID | None,
    template_key: str,
    context: dict,
    apply_branding: bool = True,
) -> RenderedEmail:
    """Produce the final subject and HTML for one message."""
    definition = email_catalog.get(template_key)
    if definition is None:
        raise ValueError(f"Unknown email template: {template_key}")

    override = await get_override(db, organization_id, template_key)
    use_override = override is not None and override.is_active

    subject_source = (
        override.subject_template
        if use_override and override.subject_template
        else definition.default_subject
    )
    body_source = (
        override.body_template
        if use_override and override.body_template
        else definition.default_body
    )

    org_name = await organization_name(db, organization_id)
    merged = {
        "organization_name": org_name,
        "today": date.today().strftime("%B %d, %Y"),
        **{k: v for k, v in context.items() if v is not None},
    }

    subject = substitute(subject_source, merged).strip()
    body = substitute(body_source, merged)

    if apply_branding:
        branding = await get_branding(db, organization_id)
        body = wrap(body, branding=branding, org_name=org_name, preheader=subject)

    return RenderedEmail(subject=subject, html_body=body, customized=bool(use_override))


async def sender_identity(
    db: AsyncSession, organization_id: uuid.UUID | None
) -> tuple[str | None, str | None]:
    """Return ``(sender_name, reply_to)`` for the organization."""
    branding = await get_branding(db, organization_id)
    if branding is None:
        return None, None
    return (branding.sender_name or None), (branding.reply_to or None)
