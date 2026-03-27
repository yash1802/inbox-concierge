"""Application rate limiting (SlowAPI). Import `limiter` from here to avoid circular imports with `main`."""

from __future__ import annotations

from starlette.requests import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.auth.jwt_session import decode_session_token
from app.config import get_settings

limiter = Limiter(key_func=get_remote_address)


def rate_limit_key_user_or_ip(request: Request) -> str:
    token = request.cookies.get("session")
    if token:
        try:
            uid = decode_session_token(get_settings(), token)
            return f"user:{uid}"
        except ValueError:
            pass
    return get_remote_address(request)
