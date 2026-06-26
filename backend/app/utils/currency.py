"""Normalization helpers for currency codes.

AI lease ingestion (and free-text entry) can yield currency values such as
``"US Dollars"`` or ``"USD ($)"`` that do not fit the 3-character ``currency``
column on ``leases``. Coercing such values to a 3-letter ISO 4217 code keeps the
lease-create/update path from raising a database ``StringDataRightTruncation``
(HTTP 500) error.
"""

import re

# Common currency names / aliases mapped to their ISO 4217 code. Keys are
# upper-cased and whitespace-collapsed before lookup. A bare "DOLLAR"/"DOLLARS"
# is assumed to mean USD (this is a US-centric app); callers that need CAD/AUD
# should supply the explicit code or qualified name (e.g. "Canadian Dollar").
_CURRENCY_NAME_MAP: dict[str, str] = {
    "US DOLLAR": "USD",
    "US DOLLARS": "USD",
    "U.S. DOLLAR": "USD",
    "UNITED STATES DOLLAR": "USD",
    "DOLLAR": "USD",
    "DOLLARS": "USD",
    "EURO": "EUR",
    "EUROS": "EUR",
    "POUND": "GBP",
    "POUNDS": "GBP",
    "POUND STERLING": "GBP",
    "BRITISH POUND": "GBP",
    "STERLING": "GBP",
    "YEN": "JPY",
    "JAPANESE YEN": "JPY",
    "CANADIAN DOLLAR": "CAD",
    "AUSTRALIAN DOLLAR": "AUD",
    "SWISS FRANC": "CHF",
    "SWISS FRANCS": "CHF",
    "RUPEE": "INR",
    "INDIAN RUPEE": "INR",
    "YUAN": "CNY",
    "RENMINBI": "CNY",
}


def normalize_currency_code(value: str | None) -> str | None:
    """Coerce an arbitrary currency string to a 3-letter uppercase code.

    Returns ``None`` for empty input. The result is always at most 3
    characters, so it safely fits the ``leases.currency`` column.
    """
    if value is None:
        return None
    collapsed = re.sub(r"\s+", " ", value).strip().upper()
    if not collapsed:
        return None
    # Already a clean 3-letter code.
    if re.fullmatch(r"[A-Z]{3}", collapsed):
        return collapsed
    # Known full name / alias (e.g. "US DOLLARS").
    mapped = _CURRENCY_NAME_MAP.get(collapsed)
    if mapped:
        return mapped
    # Embedded standalone 3-letter code (e.g. "US Dollars (USD)").
    embedded = re.search(r"\b([A-Z]{3})\b", collapsed)
    if embedded:
        return embedded.group(1)
    # Last resort: first three alphabetic characters so we never overflow.
    letters = re.sub(r"[^A-Z]", "", collapsed)
    if letters:
        return letters[:3]
    return None
