from __future__ import annotations

import uuid
from typing import Iterable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Category, Thread, ThreadCategory
from app.gmail.dto import ThreadPayload
from app.llm.schemas import ThreadClassificationItem
from app.services.category_seed import CLASSIFICATION_FALLBACK_CATEGORY_NAME


async def upsert_threads(
    session: AsyncSession,
    user_id: uuid.UUID,
    payloads: list[ThreadPayload],
) -> dict[str, uuid.UUID]:
    """Upsert threads by (user_id, gmail_thread_id). Returns map gmail_thread_id -> thread uuid."""
    mapping: dict[str, uuid.UUID] = {}
    for p in payloads:
        result = await session.execute(
            select(Thread).where(
                Thread.user_id == user_id,
                Thread.gmail_thread_id == p.gmail_thread_id,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = Thread(
                user_id=user_id,
                gmail_thread_id=p.gmail_thread_id,
                subject=p.subject,
                snippet=p.snippet,
                internal_date=p.internal_date,
                from_addr=p.from_addr,
            )
            session.add(row)
            await session.flush()
        else:
            row.subject = p.subject
            row.snippet = p.snippet
            row.internal_date = p.internal_date
            row.from_addr = p.from_addr
        mapping[p.gmail_thread_id] = row.id
    await session.flush()
    return mapping


async def load_category_name_map(session: AsyncSession, user_id: uuid.UUID) -> dict[str, uuid.UUID]:
    result = await session.execute(select(Category.id, Category.name).where(Category.user_id == user_id))
    return {name: cid for cid, name in result.all()}


async def replace_thread_categories(
    session: AsyncSession,
    thread_id: uuid.UUID,
    category_names: Iterable[str],
    name_to_id: dict[str, uuid.UUID],
) -> None:
    uniq = list(dict.fromkeys(category_names))
    resolved = [n for n in uniq if name_to_id.get(n)]
    if not resolved and CLASSIFICATION_FALLBACK_CATEGORY_NAME in name_to_id:
        resolved = [CLASSIFICATION_FALLBACK_CATEGORY_NAME]
    await session.execute(delete(ThreadCategory).where(ThreadCategory.thread_id == thread_id))
    for name in resolved:
        cid = name_to_id[name]
        session.add(ThreadCategory(thread_id=thread_id, category_id=cid))
    await session.flush()


async def apply_classifications(
    session: AsyncSession,
    user_id: uuid.UUID,
    classifications: list[ThreadClassificationItem],
    gmail_to_thread_id: dict[str, uuid.UUID],
) -> None:
    name_to_id = await load_category_name_map(session, user_id)
    for c in classifications:
        tid = gmail_to_thread_id.get(c.gmail_thread_id)
        if tid is None:
            continue
        await replace_thread_categories(session, tid, c.categories, name_to_id)
