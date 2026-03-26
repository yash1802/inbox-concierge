from __future__ import annotations

import string
from random import SystemRandom
from typing import Annotated

from cryptography.fernet import Fernet
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from google.oauth2 import id_token
from google_auth_oauthlib.flow import Flow
from google.auth.transport import requests as google_requests
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.crypto import decrypt_secret, encrypt_secret
from app.auth.deps import SessionDep, SettingsDep
from app.auth.jwt_session import create_session_token
from app.auth.oauth_state import PKCE_ENC_CLAIM, create_oauth_state, decode_oauth_state
from app.config import Settings
from app.db.models import User
from app.services.category_seed import ensure_default_categories

router = APIRouter(prefix="/auth/google", tags=["auth"])

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def _client_config(settings: Settings) -> dict:
    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [str(settings.oauth_redirect_uri)],
        }
    }


@router.get("/login")
async def google_login(settings: SettingsDep) -> RedirectResponse:
    flow = Flow.from_client_config(_client_config(settings), scopes=SCOPES)
    flow.redirect_uri = str(settings.oauth_redirect_uri)
    # Ensure PKCE verifier exists before authorization_url (Flow may have autogenerate_code_verifier=False).
    if flow.code_verifier is None:
        chars = string.ascii_letters + string.digits + "-._~"
        rnd = SystemRandom()
        flow.code_verifier = "".join(rnd.choice(chars) for _ in range(128))
    fernet = Fernet(settings.token_encryption_key.encode("utf-8"))
    enc_pkce = encrypt_secret(fernet, flow.code_verifier)
    state = create_oauth_state(settings, pkce_enc=enc_pkce)
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    response = RedirectResponse(url=authorization_url, status_code=status.HTTP_302_FOUND)
    # Optional cookie fallback for older in-flight sessions (state JWT without `p` claim).
    cookie_kwargs = {
        "httponly": True,
        "samesite": "lax",
        "max_age": 900,
        "secure": settings.environment == "production",
        "path": "/",
    }
    response.set_cookie(key="oauth_pkce", value=enc_pkce, **cookie_kwargs)
    return response


@router.get("/callback")
async def google_callback(
    session: SessionDep,
    settings: SettingsDep,
    response: Response,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
    oauth_pkce: Annotated[str | None, Cookie()] = None,
) -> RedirectResponse:
    if error:
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")
    try:
        state_payload = decode_oauth_state(settings, state)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid state") from e

    fernet = Fernet(settings.token_encryption_key.encode("utf-8"))
    enc_pkce = state_payload.get(PKCE_ENC_CLAIM) or oauth_pkce
    if not enc_pkce:
        raise HTTPException(
            status_code=400,
            detail="Missing PKCE data; restart sign-in from /api/auth/google/login",
        )
    try:
        code_verifier = decrypt_secret(fernet, enc_pkce)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid PKCE data") from e

    flow = Flow.from_client_config(_client_config(settings), scopes=SCOPES)
    flow.redirect_uri = str(settings.oauth_redirect_uri)
    flow.code_verifier = code_verifier
    flow.fetch_token(code=code)
    creds = flow.credentials

    if not creds.id_token:
        raise HTTPException(status_code=400, detail="Missing id_token")
    idinfo = id_token.verify_oauth2_token(
        creds.id_token, google_requests.Request(), settings.google_client_id
    )
    google_sub = idinfo.get("sub")
    email = idinfo.get("email")
    if not google_sub or not email:
        raise HTTPException(status_code=400, detail="Invalid id token")

    fernet = Fernet(settings.token_encryption_key.encode("utf-8"))
    enc_refresh = None
    if creds.refresh_token:
        enc_refresh = encrypt_secret(fernet, creds.refresh_token)

    result = await session.execute(select(User).where(User.google_sub == google_sub))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            google_sub=google_sub,
            email=email,
            encrypted_refresh_token=enc_refresh,
            token_scopes=" ".join(creds.scopes or SCOPES),
        )
        session.add(user)
        await session.flush()
        await ensure_default_categories(session, user.id)
    else:
        user.email = email
        if enc_refresh:
            user.encrypted_refresh_token = enc_refresh
        user.token_scopes = " ".join(creds.scopes or SCOPES)

    await session.commit()

    token = create_session_token(settings, user.id)
    redirect = RedirectResponse(url=f"{settings.frontend_origin}/", status_code=status.HTTP_302_FOUND)
    redirect.set_cookie(
        key="session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 7,
        secure=settings.environment == "production",
        path="/",
    )
    redirect.delete_cookie("oauth_pkce", path="/")
    return redirect


@router.post("/logout")
async def logout() -> Response:
    from fastapi.responses import JSONResponse

    resp = JSONResponse({"ok": True})
    resp.delete_cookie("session", path="/")
    resp.delete_cookie("oauth_pkce", path="/")
    resp.delete_cookie("oauth_state", path="/")
    return resp
