from fastapi import Response
from pydantic import BaseModel

from app.config import settings


class PortalExchangeRequest(BaseModel):
    token: str


def set_portal_cookie(response: Response, name: str, token: str, path: str, max_age: int) -> None:
    response.set_cookie(
        name,
        token,
        max_age=max_age,
        secure=settings.APP_ENV.lower() in {"production", "prod", "staging"},
        httponly=True,
        samesite="strict",
        path=path,
    )