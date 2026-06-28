"""Shared evaluation helpers for the email reminder-rule engine.

This module centralises the cross-cutting concerns that individual reminder
tasks (lease, HVAC, COI, …) need so they don't each re-implement them:

* :func:`resolve_recipients` — expand a rule's free-text emails plus its
  structured role/user-linked recipients into a concrete address list.
* Acknowledgement tracking — :func:`get_or_create_acknowledgement` and
  :func:`acknowledge_url` provide the tokenized "I've handled this" workflow,
  mirroring the waiver/client-portal public-token pattern.
* Escalation — :func:`due_escalation_level` decides which escalation step a
  notice is currently at, so a rule can re-fire to a wider audience while the
  underlying condition stays unacknowledged.
* :class:`DigestBuffer` — batches per-recipient notices so a rule in a digest
  delivery mode sends one combined email instead of one-per-event.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.email import EmailAcknowledgement, EmailReminderRule
from app.models.user import User
from app.utils.email_client import send_email


def acknowledge_url(token: str) -> str:
    """Public, login-free URL a recipient visits to acknowledge a notice."""
    return f"{settings.FRONTEND_URL.rstrip('/')}/ack/{token}"


def _dedupe_preserve_order(emails: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in emails:
        if not raw:
            continue
        addr = raw.strip()
        key = addr.lower()
        if not addr or key in seen:
            continue
        seen.add(key)
        out.append(addr)
    return out


async def resolve_recipients(
    db: AsyncSession,
    rule: EmailReminderRule,
    *,
    extra_emails: list[str] | None = None,
) -> list[str]:
    """Resolve a rule's recipients to a de-duplicated list of email addresses.

    Combines, in order:

    1. ``rule.recipient_emails`` (free-text, always honoured for back-compat),
    2. active users whose ``role`` is in ``rule.recipient_roles``,
    3. active users whose id is in ``rule.recipient_user_ids``,
    4. any ``extra_emails`` supplied by the caller (e.g. escalation targets).

    Role/user lookups are scoped to ``rule.organization_id`` when the rule is
    org-scoped, otherwise they match across all orgs.
    """
    emails: list[str] = list(rule.recipient_emails or [])

    role_names = [r for r in (rule.recipient_roles or []) if r]
    user_ids = [u for u in (rule.recipient_user_ids or []) if u]

    if role_names or user_ids:
        conditions = []
        if role_names:
            conditions.append(User.role.in_(role_names))
        if user_ids:
            conditions.append(User.id.in_(user_ids))

        from sqlalchemy import or_

        stmt = select(User.email).where(User.is_active.is_(True), or_(*conditions))
        if rule.organization_id is not None:
            stmt = stmt.where(User.organization_id == rule.organization_id)
        try:
            result = await db.execute(stmt)
            emails.extend(row[0] for row in result.all())
        except Exception:
            # A failed lookup should not block the free-text recipients.
            pass

    if extra_emails:
        emails.extend(extra_emails)

    return _dedupe_preserve_order(emails)


def due_escalation_level(rule: EmailReminderRule, days_since_first: int) -> int:
    """Return the highest escalation step whose offset has elapsed.

    ``rule.escalation_offsets`` is a list of day offsets *after* the initial
    notice (level 0). For offsets ``[3, 7]`` the result is ``0`` for
    ``days_since_first < 3``, ``1`` for ``3 <= days < 7`` and ``2`` for
    ``days >= 7``.
    """
    offsets = sorted(o for o in (rule.escalation_offsets or []) if o is not None and o > 0)
    level = 0
    for offset in offsets:
        if days_since_first >= offset:
            level += 1
        else:
            break
    return level


def escalation_recipients(rule: EmailReminderRule, level: int) -> list[str]:
    """Extra recipients to add once a notice has escalated past level 0."""
    if level <= 0:
        return []
    return list(rule.escalation_recipient_emails or [])


async def get_or_create_acknowledgement(
    db: AsyncSession,
    rule: EmailReminderRule,
    *,
    entity_type: str,
    entity_id: uuid.UUID | None,
    subject: str,
) -> EmailAcknowledgement:
    """Find the existing notice-state row for a (rule, entity), or create one.

    A single row tracks a notice across its whole lifecycle: escalation state
    (``escalation_level``) and acknowledgement status (``acknowledged_at``).
    Returning an already-acknowledged row lets the caller stop re-notifying for
    the same entity. The caller is responsible for committing.
    """
    stmt = (
        select(EmailAcknowledgement)
        .where(
            EmailAcknowledgement.rule_id == rule.id,
            EmailAcknowledgement.entity_type == entity_type,
        )
        .order_by(EmailAcknowledgement.first_sent_at.desc())
    )
    if entity_id is not None:
        stmt = stmt.where(EmailAcknowledgement.entity_id == entity_id)
    else:
        stmt = stmt.where(EmailAcknowledgement.entity_id.is_(None))

    result = await db.execute(stmt)
    ack = result.scalars().first()
    if ack is not None:
        return ack

    ack = EmailAcknowledgement(
        organization_id=rule.organization_id,
        rule_id=rule.id,
        entity_type=entity_type,
        entity_id=entity_id,
        subject=subject,
        ack_token=secrets.token_hex(32),
        escalation_level=-1,  # -1 = no notice emitted yet (initial notice is level 0)
        first_sent_at=datetime.now(timezone.utc),
    )
    db.add(ack)
    return ack


def acknowledge_link_html(ack: EmailAcknowledgement) -> str:
    """A small HTML snippet appended to notices needing acknowledgement."""
    url = acknowledge_url(ack.ack_token)
    return (
        '<hr><p style="font-size:13px;color:#555">'
        "Please confirm you've actioned this reminder so it stops escalating: "
        f'<a href="{url}">Acknowledge</a>.'
        "</p>"
    )


class DigestBuffer:
    """Collects per-recipient notice fragments for batched (digest) delivery.

    Usage within a single task run::

        buf = DigestBuffer()
        buf.add(recipients, "<li>Lease X expires in 10 days</li>")
        ...
        await buf.flush(subject="Daily reminder digest")

    When a rule's ``delivery_mode`` is ``immediate`` the task should bypass the
    buffer and send directly; the buffer exists for the digest modes.
    """

    def __init__(self) -> None:
        self._items: dict[str, list[str]] = {}

    def add(self, recipients: list[str], html_fragment: str) -> None:
        for recipient in recipients:
            self._items.setdefault(recipient, []).append(html_fragment)

    @property
    def is_empty(self) -> bool:
        return not self._items

    async def flush(self, *, subject: str, intro: str = "") -> dict[str, bool]:
        """Send one combined email per recipient. Returns recipient→success."""
        outcomes: dict[str, bool] = {}
        for recipient, fragments in self._items.items():
            body = intro + "<ul>" + "".join(fragments) + "</ul>"
            try:
                outcomes[recipient] = await send_email(recipient, subject, body)
            except Exception:
                outcomes[recipient] = False
        self._items.clear()
        return outcomes


def days_between(target: date | None, today: date | None = None) -> int:
    """Whole days from ``today`` until ``target`` (negative if in the past)."""
    if target is None:
        return 0
    if today is None:
        today = date.today()
    return (target - today).days
