"""Usage metering: feature-adoption and AI token accounting.

This module is the single helper for recording :class:`UsageEvent` rows and for
the aggregate queries that power the super-admin "Usage & Adoption" and token
monitoring views, plus tier-based token-limit enforcement.

Recording is **best-effort**: a metering failure must never break the request
that triggered it, so :func:`record_event` swallows errors after rolling back
(mirroring the activity-log / search-vector side-effect pattern used elsewhere).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.usage_event import UsageEvent


def current_period(now: datetime | None = None) -> str:
    """Return the current billing period as a ``YYYY-MM`` string (UTC)."""
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m")


def previous_period(now: datetime | None = None) -> str:
    """Return the prior month as a ``YYYY-MM`` string (UTC)."""
    ref = now or datetime.now(timezone.utc)
    year, month = ref.year, ref.month
    if month == 1:
        year, month = year - 1, 12
    else:
        month -= 1
    return f"{year:04d}-{month:02d}"


def recent_periods(count: int, now: datetime | None = None) -> list[str]:
    """Return the last ``count`` period strings, oldest first (incl. current)."""
    ref = now or datetime.now(timezone.utc)
    year, month = ref.year, ref.month
    periods: list[str] = []
    for _ in range(max(count, 1)):
        periods.append(f"{year:04d}-{month:02d}")
        if month == 1:
            year, month = year - 1, 12
        else:
            month -= 1
    return list(reversed(periods))


async def record_event(
    db: AsyncSession,
    org_id: uuid.UUID | None,
    feature: str,
    *,
    quantity: int = 1,
    input_tokens: int = 0,
    output_tokens: int = 0,
    duration_ms: int | None = None,
    success: bool | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """Best-effort: record a single usage event.

    ``input_tokens`` / ``output_tokens`` capture AI provider token consumption
    (0 for non-AI feature events). Lightweight performance signals (request
    latency, success flag) and any extra context are JSON-encoded into ``meta``.
    """
    if org_id is None:
        return

    payload: dict[str, Any] = dict(meta or {})
    if duration_ms is not None:
        payload["duration_ms"] = duration_ms
    if success is not None:
        payload["success"] = success
    meta_str: str | None = None
    if payload:
        meta_str = json.dumps(payload)
        if len(meta_str) > 500:
            # Never store truncated (invalid) JSON: fall back to the cheap,
            # bounded performance signals and drop the oversized extras.
            fallback = {
                k: payload[k]
                for k in ("duration_ms", "success")
                if k in payload
            }
            candidate = json.dumps(fallback) if fallback else None
            meta_str = candidate if candidate and len(candidate) <= 500 else None

    event = UsageEvent(
        organization_id=org_id,
        feature=feature,
        quantity=quantity,
        input_tokens=max(int(input_tokens or 0), 0),
        output_tokens=max(int(output_tokens or 0), 0),
        period_month=current_period(),
        meta=meta_str,
    )
    db.add(event)
    try:
        await db.commit()
    except Exception:
        await db.rollback()


async def org_period_tokens(
    db: AsyncSession,
    org_id: uuid.UUID,
    period: str | None = None,
) -> tuple[int, int]:
    """Return ``(input_tokens, output_tokens)`` consumed by an org in a period."""
    period = period or current_period()
    row = (
        await db.execute(
            select(
                func.coalesce(func.sum(UsageEvent.input_tokens), 0),
                func.coalesce(func.sum(UsageEvent.output_tokens), 0),
            ).where(
                UsageEvent.organization_id == org_id,
                UsageEvent.period_month == period,
            )
        )
    ).one()
    return int(row[0]), int(row[1])


# ── Tracked-feature catalog ───────────────────────────────────────────────────
#
# Human-readable labels for the ``feature`` keys we record. Features listed here
# but never seen in ``usage_events`` surface as zero-adoption "removal
# candidates" in the management console. Keep new ``record_event`` feature keys
# in sync with this map.
TRACKED_FEATURES: dict[str, str] = {
    # AI-metered features (consume tokens)
    "ai_lease_parse": "AI: lease parse",
    "ai_ap_parse": "AI: invoice parse",
    "ai_insurance_parse": "AI: insurance parse",
    "ai_hvac_parse": "AI: HVAC contract parse",
    "ai_triage": "AI: ticket triage",
    "ai_similar": "AI: duplicate detection",
    "ai_draft": "AI: email → ticket draft",
    "ai_abstract": "AI: lease abstract",
    "ai_summary": "AI: operations summary",
    "ai_assistant": "AI: portfolio assistant",
    "ai_reindex": "AI: knowledge reindex",
    # Non-AI feature actions
    "waiver_sent": "Digital waiver sent",
    "document_search": "Lease document search",
    "report_export": "Report export (PDF/XLSX)",
    "transition_created": "Transition created",
}


def feature_label(key: str) -> str:
    return TRACKED_FEATURES.get(key, key)


async def feature_adoption(
    db: AsyncSession,
    *,
    months: int = 6,
    org_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Aggregate usage by feature over the last ``months`` periods.

    Returns one row per feature with total events, token totals, and the number
    of distinct orgs that used it (adoption breadth). A simple ``value_signal``
    (adoption breadth × event volume) makes high-value vs. unused features
    obvious. When ``org_id`` is given the aggregation is scoped to that org.
    """
    periods = recent_periods(months, now)
    conditions = [UsageEvent.period_month.in_(periods)]
    if org_id is not None:
        conditions.append(UsageEvent.organization_id == org_id)

    rows = (
        await db.execute(
            select(
                UsageEvent.feature,
                func.coalesce(func.sum(UsageEvent.quantity), 0),
                func.count(func.distinct(UsageEvent.organization_id)),
                func.coalesce(func.sum(UsageEvent.input_tokens), 0),
                func.coalesce(func.sum(UsageEvent.output_tokens), 0),
            )
            .where(*conditions)
            .group_by(UsageEvent.feature)
        )
    ).all()

    seen = {r[0]: r for r in rows}
    features = set(seen) | set(TRACKED_FEATURES)
    result: list[dict[str, Any]] = []
    for feature in features:
        r = seen.get(feature)
        events = int(r[1]) if r else 0
        org_count = int(r[2]) if r else 0
        in_tok = int(r[3]) if r else 0
        out_tok = int(r[4]) if r else 0
        result.append(
            {
                "feature": feature,
                "label": feature_label(feature),
                "events": events,
                "org_count": org_count,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                # Value signal: adoption breadth weighted by usage volume.
                "value_signal": org_count * events,
                "removal_candidate": events == 0,
            }
        )
    result.sort(key=lambda x: (x["value_signal"], x["events"]), reverse=True)
    return result


async def platform_token_totals(
    db: AsyncSession, period: str | None = None
) -> dict[str, int]:
    """Return platform-wide input/output token totals for a period."""
    period = period or current_period()
    row = (
        await db.execute(
            select(
                func.coalesce(func.sum(UsageEvent.input_tokens), 0),
                func.coalesce(func.sum(UsageEvent.output_tokens), 0),
            ).where(UsageEvent.period_month == period)
        )
    ).one()
    return {"input_tokens": int(row[0]), "output_tokens": int(row[1])}


async def top_token_orgs(
    db: AsyncSession,
    *,
    period: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return the orgs consuming the most tokens in a period (highest first)."""
    period = period or current_period()
    total = (UsageEvent.input_tokens + UsageEvent.output_tokens).label("total")
    rows = (
        await db.execute(
            select(
                UsageEvent.organization_id,
                func.coalesce(func.sum(UsageEvent.input_tokens), 0),
                func.coalesce(func.sum(UsageEvent.output_tokens), 0),
            )
            .where(UsageEvent.period_month == period)
            .group_by(UsageEvent.organization_id)
            .order_by(func.coalesce(func.sum(total), 0).desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "organization_id": r[0],
            "input_tokens": int(r[1]),
            "output_tokens": int(r[2]),
            "total_tokens": int(r[1]) + int(r[2]),
        }
        for r in rows
    ]


async def org_token_summary(
    db: AsyncSession,
    org_id: uuid.UUID,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Per-org token usage for the current and prior period plus a feature split."""
    cur = current_period(now)
    prev = previous_period(now)
    cur_in, cur_out = await org_period_tokens(db, org_id, cur)
    prev_in, prev_out = await org_period_tokens(db, org_id, prev)

    feature_rows = (
        await db.execute(
            select(
                UsageEvent.feature,
                func.coalesce(func.sum(UsageEvent.quantity), 0),
                func.coalesce(func.sum(UsageEvent.input_tokens), 0),
                func.coalesce(func.sum(UsageEvent.output_tokens), 0),
            )
            .where(
                UsageEvent.organization_id == org_id,
                UsageEvent.period_month == cur,
            )
            .group_by(UsageEvent.feature)
            .order_by(
                func.coalesce(
                    func.sum(UsageEvent.input_tokens + UsageEvent.output_tokens), 0
                ).desc()
            )
        )
    ).all()

    return {
        "period": cur,
        "previous_period": prev,
        "current": {
            "input_tokens": cur_in,
            "output_tokens": cur_out,
            "total_tokens": cur_in + cur_out,
        },
        "previous": {
            "input_tokens": prev_in,
            "output_tokens": prev_out,
            "total_tokens": prev_in + prev_out,
        },
        "by_feature": [
            {
                "feature": r[0],
                "label": feature_label(r[0]),
                "events": int(r[1]),
                "input_tokens": int(r[2]),
                "output_tokens": int(r[3]),
            }
            for r in feature_rows
        ],
    }
