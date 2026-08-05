"""Live bank feed connector (Plaid) — link, exchange, and incremental sync."""

from app.services.bank_feed.plaid_client import PlaidApiError, PlaidClient, is_configured

__all__ = ["PlaidApiError", "PlaidClient", "is_configured"]
