from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import selectinload

from app.auth.deps import CurrentUser, SessionDep
from app.db.models import Thread, ThreadCategory

router = APIRouter(prefix="/threads", tags=["threads"])


class ThreadOut(BaseModel):
    id: str
    gmail_thread_id: str
    subject: str
    snippet: str
    internal_date: int
    from_addr: str | None
    categories: list[str]


class ThreadsPageOut(BaseModel):
    items: list[ThreadOut]
    next_cursor_internal_date: int | None
    next_cursor_id: str | None


@router.get("", response_model=ThreadsPageOut)
async def list_threads(
    user: CurrentUser,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    cursor_internal_date: Annotated[int | None, Query()] = None,
    cursor_id: Annotated[str | None, Query()] = None,
    category_ids: Annotated[list[uuid.UUID] | None, Query()] = None,
    from_ts: Annotated[int | None, Query(description="internal_date lower bound ms")] = None,
    to_ts: Annotated[int | None, Query(description="internal_date upper bound ms")] = None,
) -> ThreadsPageOut:
    cid: uuid.UUID | None = None
    if cursor_id is not None:
        try:
            cid = uuid.UUID(cursor_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail="Invalid cursor_id") from e

    stmt = (
        select(Thread)
        .where(Thread.user_id == user.id)
        .options(selectinload(Thread.category_links).selectinload(ThreadCategory.category))
        .order_by(Thread.internal_date.desc(), Thread.id.desc())
        .limit(limit + 1)
    )
    if cursor_internal_date is not None and cid is not None:
        stmt = stmt.where(
            or_(
                Thread.internal_date < cursor_internal_date,
                and_(
                    Thread.internal_date == cursor_internal_date,
                    Thread.id < cid,
                ),
            )
        )
    if from_ts is not None:
        stmt = stmt.where(Thread.internal_date >= from_ts)
    if to_ts is not None:
        stmt = stmt.where(Thread.internal_date <= to_ts)
    if category_ids:
        stmt = stmt.where(
            Thread.id.in_(
                select(ThreadCategory.thread_id).where(
                    ThreadCategory.category_id.in_(category_ids)
                )
            )
        )

    result = await session.execute(stmt)
    rows = list(result.scalars().unique().all())
    has_more = len(rows) > limit
    page = rows[:limit]

    def cat_names(t: Thread) -> list[str]:
        names: list[str] = []
        for link in t.category_links:
            if link.category is not None:
                names.append(link.category.name)
        return sorted(names)

    items = [
        ThreadOut(
            id=str(t.id),
            gmail_thread_id=t.gmail_thread_id,
            subject=t.subject,
            snippet=t.snippet,
            internal_date=t.internal_date,
            from_addr=t.from_addr,
            categories=cat_names(t),
        )
        for t in page
    ]
    next_d: int | None = None
    next_i: str | None = None
    if has_more and page:
        last = page[-1]
        next_d = last.internal_date
        next_i = str(last.id)
    return ThreadsPageOut(
        items=items,
        next_cursor_internal_date=next_d,
        next_cursor_id=next_i,
    )
