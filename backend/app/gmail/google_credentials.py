import asyncio

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from app.config import Settings


def build_credentials_from_refresh(
    settings: Settings,
    refresh_token: str,
    scopes: list[str],
) -> Credentials:
    return Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=scopes,
    )


async def ensure_fresh_access_token(creds: Credentials) -> str:
    if creds.valid:
        return creds.token or ""
    await asyncio.to_thread(creds.refresh, Request())
    if not creds.token:
        raise RuntimeError("Failed to obtain access token")
    return creds.token
