import uuid
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt_session import decode_session_token
from app.config import Settings, get_settings
from app.db.models import User
from app.db.session import get_session

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


async def get_current_user(
    session: SessionDep,
    settings: SettingsDep,
    session_token: Annotated[str | None, Cookie(alias="session")] = None,
) -> User:
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        user_id = decode_session_token(settings, session_token)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session") from e
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def optional_user_id_from_cookie(
    settings: Settings,
    session_token: str | None,
) -> uuid.UUID | None:
    if not session_token:
        return None
    try:
        return decode_session_token(settings, session_token)
    except ValueError:
        return None
