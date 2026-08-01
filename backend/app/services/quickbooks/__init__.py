"""QuickBooks Online connector (OAuth2 + incremental journal-entry sync)."""

from app.services.quickbooks.client import QuickBooksApiError, QuickBooksClient

__all__ = ["QuickBooksApiError", "QuickBooksClient"]
