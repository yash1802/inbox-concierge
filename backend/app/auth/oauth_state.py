import secrets
from datetime import UTC, datetime, timedelta

import jwt

from app.config import Settings

# Fernet-encrypted PKCE verifier, embedded in signed state JWT (Google echoes `state` on callback).
# Avoids relying on a separate HttpOnly cookie (host / SameSite / partition issues).
PKCE_ENC_CLAIM = "p"


def create_oauth_state(settings: Settings, *, pkce_enc: str | None = None) -> str:
    nonce = secrets.token_urlsafe(16)
    now = datetime.now(tz=UTC)
    payload: dict = {
        "nonce": nonce,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=15)).timestamp()),
    }
    if pkce_enc is not None:
        payload[PKCE_ENC_CLAIM] = pkce_enc
    return jwt.encode(payload, settings.session_secret, algorithm="HS256")


def decode_oauth_state(settings: Settings, state: str) -> dict:
    try:
        return jwt.decode(state, settings.session_secret, algorithms=["HS256"])
    except jwt.InvalidTokenError as e:
        raise ValueError("Invalid OAuth state") from e


def verify_oauth_state(settings: Settings, state: str) -> None:
    decode_oauth_state(settings, state)
