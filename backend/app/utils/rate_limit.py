"""Per-org rate limiting utilities.

Provides a SlowAPI ``Limiter`` instance keyed on the organization ID extracted
from the JWT, falling back to IP address for unauthenticated requests.

Usage in routers:
    from app.utils.rate_limit import org_limiter

    @router.post("/my-route")
    @org_limiter.limit("60/minute")
    async def my_route(request: Request, ...):
        ...

The limiter must also be registered on ``app.state`` in main.py:
    from app.utils.rate_limit import org_limiter
    app.state.org_limiter = org_limiter
"""
from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _get_org_key(request: Request) -> str:
    """Rate-limit key: org_id from JWT bearer token, or remote IP as fallback."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        try:
            from app.auth.jwt_handler import decode_access_token
            payload = decode_access_token(auth[7:])
            if payload:
                org_id = payload.get("org_id")
                if org_id:
                    return f"org:{org_id}"
        except Exception:
            pass
    return get_remote_address(request)


org_limiter = Limiter(key_func=_get_org_key)
