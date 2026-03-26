import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.config import Settings


def create_session_token(settings: Settings, user_id: uuid.UUID, expires_hours: int = 168) -> str:
    now = datetime.now(tz=UTC)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=expires_hours)).timestamp()),
    }
    return jwt.encode(payload, settings.session_secret, algorithm="HS256")


def decode_session_token(settings: Settings, token: str) -> uuid.UUID:
    try:
        payload = jwt.decode(token, settings.session_secret, algorithms=["HS256"])
        sub = payload.get("sub")
        if not sub:
            raise jwt.InvalidTokenError("missing sub")
        return uuid.UUID(sub)
    except (jwt.InvalidTokenError, ValueError) as e:
        raise ValueError("Invalid session") from e
