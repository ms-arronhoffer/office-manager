"""Shared paging limits for the external portals.

Portal accounts belong to landlords, vendors, residents and owners whose
portfolios can be far larger than the handful of rows a demo shows. Loading a
whole collection into the browser is what makes a portal feel slow for exactly
the customers a competitive bid is won or lost on, so every portal collection
is served in bounded pages with the full size reported separately.
"""

from __future__ import annotations

# Default rows returned when a portal client does not ask for a specific page.
PORTAL_PAGE_SIZE = 100

# Hard ceiling; protects the API from a client asking for everything at once.
PORTAL_MAX_PAGE_SIZE = 500

# Total row count for the collection, so a client can render pagination without
# a second round trip.
TOTAL_COUNT_HEADER = "X-Total-Count"
