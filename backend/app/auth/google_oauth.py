from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from app.config import settings


async def verify_google_token(token: str) -> dict | None:
    try:
        idinfo = id_token.verify_oauth2_token(
            token, google_requests.Request(), settings.GOOGLE_CLIENT_ID
        )
        return {
            "sub": idinfo["sub"],
            "email": idinfo["email"],
            "name": idinfo.get("name", idinfo["email"]),
        }
    except Exception:
        return None
