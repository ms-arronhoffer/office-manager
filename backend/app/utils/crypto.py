"""Symmetric encryption helper for secrets we must store and later send back
out verbatim (e.g. a third-party API client secret), as opposed to passwords
and API keys which are one-way hashed (see ``app.models.api_key``).

Backed by Fernet (AES-128-CBC + HMAC) from the ``cryptography`` package,
which is already a transitive dependency via ``python-jose[cryptography]``.

The key is read from ``settings.ENCRYPTION_KEY`` — a urlsafe-base64 32-byte
key as produced by ``Fernet.generate_key()``. When unset, encryption degrades
to a clearly-marked no-op passthrough (mirroring the SMTP/Stripe/Gemini
"optional integration" convention) so local/dev environments without the key
configured don't crash — but a warning is logged, and this must never be relied
on in production.
"""
from __future__ import annotations

import logging

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)

_UNENCRYPTED_PREFIX = "plain:"


def _get_fernet() -> Fernet | None:
    key = settings.ENCRYPTION_KEY
    if not key:
        return None
    try:
        return Fernet(key.encode("utf-8") if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        logger.error("Invalid ENCRYPTION_KEY configured: %s", exc)
        return None


def encrypt_secret(plaintext: str) -> str:
    """Encrypt ``plaintext`` for storage. Returns a string safe to persist."""
    fernet = _get_fernet()
    if fernet is None:
        logger.warning(
            "ENCRYPTION_KEY not configured — storing secret unencrypted. "
            "Set ENCRYPTION_KEY before using this in production."
        )
        return _UNENCRYPTED_PREFIX + plaintext
    token = fernet.encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a value previously produced by :func:`encrypt_secret`."""
    if ciphertext.startswith(_UNENCRYPTED_PREFIX):
        return ciphertext[len(_UNENCRYPTED_PREFIX):]
    fernet = _get_fernet()
    if fernet is None:
        raise ValueError(
            "ENCRYPTION_KEY is not configured; cannot decrypt stored secret."
        )
    try:
        return fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Stored secret could not be decrypted (bad key or corrupted data).") from exc


def mask_secret(plaintext: str, visible: int = 4) -> str:
    """Return a display-safe hint like ``••••ab12`` for UI listings."""
    if not plaintext:
        return ""
    tail = plaintext[-visible:] if len(plaintext) > visible else plaintext
    return f"{'•' * 8}{tail}"
