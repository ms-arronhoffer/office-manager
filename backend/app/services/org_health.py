from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.models.organization import Organization


def _days_since(dt: datetime | None, now: datetime) -> int | None:
    if dt is None:
        return None
    value = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return max(0, int((now - value).total_seconds() // 86400))


def _clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> int:
    return int(round(max(minimum, min(maximum, value))))


def compute_health_score(org: Organization, stats: dict[str, Any]) -> dict[str, Any]:
    now = stats.get("now") or datetime.now(timezone.utc)

    last_activity_days = _days_since(stats.get("last_activity_at"), now)
    last_login_days = _days_since(stats.get("last_login_at"), now)
    recency_days = min(v for v in [last_activity_days, last_login_days] if v is not None) if any(v is not None for v in [last_activity_days, last_login_days]) else None
    if recency_days is None:
        usage_score = 10
    elif recency_days <= 7:
        usage_score = 30
    elif recency_days <= 21:
        usage_score = 24
    elif recency_days <= 45:
        usage_score = 16
    elif recency_days <= 90:
        usage_score = 8
    else:
        usage_score = 2

    seat_count = int(stats.get("seat_count") or 0)
    max_seats = stats.get("effective_max_seats")
    if max_seats in (None, 0):
        seat_utilization_ratio = 1.0 if seat_count > 0 else 0.35
    else:
        seat_utilization_ratio = seat_count / max(int(max_seats), 1)
    if seat_utilization_ratio >= 0.55:
        seat_score = 20
    elif seat_utilization_ratio >= 0.35:
        seat_score = 16
    elif seat_utilization_ratio >= 0.2:
        seat_score = 11
    elif seat_utilization_ratio > 0:
        seat_score = 6
    else:
        seat_score = 2

    payment_status = org.payment_status
    payment_score = {
        "active": 25,
        "trial": 18,
        "past_due": 8,
        "canceled": 0,
    }.get(payment_status, 14)
    if not org.is_active:
        payment_score = 0

    current_tokens = int(stats.get("current_total_tokens") or 0)
    previous_tokens = int(stats.get("previous_total_tokens") or 0)
    if current_tokens == 0 and previous_tokens == 0:
        token_score = 6
        token_trend = "flat"
    elif previous_tokens == 0:
        token_score = 15
        token_trend = "ramping"
    else:
        delta_ratio = (current_tokens - previous_tokens) / max(previous_tokens, 1)
        token_trend = "up" if delta_ratio > 0.1 else "down" if delta_ratio < -0.1 else "flat"
        if delta_ratio >= 0.25:
            token_score = 15
        elif delta_ratio >= -0.1:
            token_score = 12
        elif delta_ratio >= -0.35:
            token_score = 8
        else:
            token_score = 4

    ticket_count = int(stats.get("ticket_count") or 0)
    open_ticket_count = int(stats.get("open_ticket_count") or 0)
    if open_ticket_count <= 2:
        ticket_score = 10
    elif open_ticket_count <= 5:
        ticket_score = 7
    elif open_ticket_count <= 10:
        ticket_score = 4
    else:
        ticket_score = 1
    if ticket_count >= 20 and open_ticket_count <= 5:
        ticket_score = min(10, ticket_score + 1)

    score = _clamp(usage_score + seat_score + payment_score + token_score + ticket_score)
    band = "healthy" if score >= 75 else "at_risk" if score >= 45 else "critical"
    if payment_status in {"past_due", "canceled"} or not org.is_active:
        band = "critical" if score < 60 else "at_risk"

    return {
        "score": score,
        "band": band,
        "factors": {
            "usage_recency_days": recency_days,
            "seat_utilization_ratio": round(seat_utilization_ratio, 3),
            "payment_status": payment_status,
            "token_trend": token_trend,
            "current_total_tokens": current_tokens,
            "previous_total_tokens": previous_tokens,
            "ticket_count": ticket_count,
            "open_ticket_count": open_ticket_count,
        },
    }
