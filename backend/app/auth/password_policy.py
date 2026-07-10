from __future__ import annotations

import re

PASSWORD_MIN_LENGTH = 12

_UPPERCASE_RE = re.compile(r"[A-Z]")
_LOWERCASE_RE = re.compile(r"[a-z]")
_DIGIT_RE = re.compile(r"\d")
_SPECIAL_RE = re.compile(r"[^A-Za-z0-9]")


def validate_password_strength(password: str) -> str:
    """Require 12+ chars and at least 3 of 4 character categories."""
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters long.")

    categories = sum(
        (
            bool(_UPPERCASE_RE.search(password)),
            bool(_LOWERCASE_RE.search(password)),
            bool(_DIGIT_RE.search(password)),
            bool(_SPECIAL_RE.search(password)),
        )
    )
    if categories < 3:
        raise ValueError(
            "Password must include at least 3 of the following: uppercase letter, lowercase letter, number, or special character."
        )
    return password
