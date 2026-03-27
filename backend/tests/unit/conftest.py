from __future__ import annotations

from typing import Any

from unittest.mock import AsyncMock, MagicMock


def fake_db_session() -> MagicMock:
    """MagicMock session with sync `begin()` returning an async context manager (like AsyncSession)."""
    session = MagicMock()
    session.begin.return_value = MagicMock(
        __aenter__=AsyncMock(return_value=session),
        __aexit__=AsyncMock(return_value=None),
    )
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    return session


class _AsyncSessionContext:
    def __init__(self, session: Any) -> None:
        self._session = session

    async def __aenter__(self) -> Any:
        return self._session

    async def __aexit__(self, *args: object) -> None:
        return None


def async_session_maker_for(session: Any) -> Any:
    """Return a callable that matches async_session_maker() -> async context manager."""

    def _maker() -> _AsyncSessionContext:
        return _AsyncSessionContext(session)

    return _maker
